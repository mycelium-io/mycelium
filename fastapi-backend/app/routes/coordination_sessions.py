# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Coordination-session API — top-level resource.

Exposes negotiation sessions as first-class entities. Consumers (OpenClaw
plugin, frontend, CLI) address sessions by id here rather than via their
parent room's display name, so the ``/api/rooms/...`` surface no longer
needs to know about session-name encoding.
"""

import asyncio
import json
import logging
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import room_channel
from app.config import settings
from app.database import async_session_maker, get_async_session
from app.models import CoordinationSession, Message
from app.schemas import (
    CoordinationSessionRead,
    MessageCreate,
    MessageListResponse,
    MessageRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coordination-sessions", tags=["coordination-sessions"])


# ── Read ──────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[CoordinationSessionRead])
async def list_coordination_sessions(
    db: AsyncSession = Depends(get_async_session),
    parent_room: str | None = Query(None, description="Filter by parent room name"),
    state: str | None = Query(
        None,
        description="Comma-separated state filter (e.g. 'waiting,negotiating')",
    ),
    limit: int = Query(200, le=1000),
):
    """List coordination sessions, newest first.

    Supports two filters used by the OpenClaw channel plugin's polling loop
    (``state=waiting,negotiating``) and the frontend sessions rail
    (``parent_room=<name>``).
    """
    query = select(CoordinationSession).order_by(CoordinationSession.created_at.desc())

    if parent_room:
        query = query.where(CoordinationSession.parent_room_name == parent_room)
    if state:
        wanted = [s.strip() for s in state.split(",") if s.strip()]
        if wanted:
            query = query.where(CoordinationSession.state.in_(wanted))

    result = await db.execute(query.limit(limit))
    return [CoordinationSessionRead.model_validate(s) for s in result.scalars().all()]


@router.get("/{session_id}", response_model=CoordinationSessionRead)
async def get_coordination_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    result = await db.execute(
        select(CoordinationSession).where(CoordinationSession.id == session_id)
    )
    coord = result.scalar_one_or_none()
    if not coord:
        raise HTTPException(status_code=404, detail="CoordinationSession not found")
    return CoordinationSessionRead.model_validate(coord)


# ── Messages ──────────────────────────────────────────────────────────────────


async def _resolve_session(session_id: UUID, db: AsyncSession) -> CoordinationSession:
    result = await db.execute(
        select(CoordinationSession).where(CoordinationSession.id == session_id)
    )
    coord = result.scalar_one_or_none()
    if not coord:
        raise HTTPException(status_code=404, detail="CoordinationSession not found")
    return coord


@router.post("/{session_id}/messages", response_model=MessageRead, status_code=201)
async def post_session_message(
    session_id: UUID,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Post a message to a coordination session.

    Messages are stored with ``coordination_session_id`` set and ``room_name``
    null. SSE subscribers on the session-display channel still receive them
    via the same ``room:{display_name}`` NOTIFY topic during the deprecation
    window so existing OpenClaw plugin / CLI subscribers don't break.
    """
    coord = await _resolve_session(session_id, db)

    msg = Message(
        room_name=None,
        coordination_session_id=coord.id,
        sender_handle=payload.sender_handle,
        recipient_handle=payload.recipient_handle,
        message_type=payload.message_type,
        content=payload.content,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    display_name = coord.display_name
    try:
        parsed = urlparse(settings.DATABASE_URL)
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
        try:
            await conn.execute(
                "SELECT pg_notify($1, $2)",
                room_channel(display_name),
                json.dumps(
                    {
                        "id": str(msg.id),
                        "coordination_session_id": str(coord.id),
                        "sender_handle": msg.sender_handle,
                        "recipient_handle": msg.recipient_handle,
                        "message_type": msg.message_type,
                        "content": msg.content,
                        "created_at": msg.created_at.isoformat(),
                    }
                ),
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("NOTIFY failed for session %s: %s", coord.id, e)

    if coord.state == "negotiating":
        from app.services import coordination

        # coordination.on_agent_response still keys on display name during the
        # deprecation window; pass that. Internal rekey lands later in this PR.
        asyncio.ensure_future(
            coordination.on_agent_response(display_name, msg.sender_handle, msg.content)
        )

    return msg


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def list_session_messages(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_session),
    limit: int = Query(50, le=500),
    offset: int = 0,
    sender: str | None = None,
    message_type: str | None = None,
):
    coord = await _resolve_session(session_id, db)

    query = select(Message).where(
        (Message.coordination_session_id == coord.id) | (Message.room_name == coord.display_name)
    )
    if sender:
        query = query.where(Message.sender_handle == sender)
    if message_type:
        query = query.where(Message.message_type == message_type)

    query = query.order_by(Message.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    messages: list[Message] = list(result.scalars().all())

    return MessageListResponse(
        messages=[MessageRead.model_validate(m) for m in messages],
        total=len(messages),
    )


@router.get("/{session_id}/messages/stream")
async def stream_session_messages(
    session_id: UUID,
    request: Request,
):
    """SSE stream for a coordination session.

    Resolves the session and subscribes to the underlying ``room:{display_name}``
    Postgres NOTIFY channel so any inbound message routed to either coord_session_id
    or the legacy display name surfaces here.
    """
    async with async_session_maker() as db:
        result = await db.execute(
            select(CoordinationSession).where(CoordinationSession.id == session_id)
        )
        coord = result.scalar_one_or_none()
    if not coord:
        raise HTTPException(status_code=404, detail="CoordinationSession not found")

    display_name = coord.display_name

    async def event_gen():
        parsed = urlparse(settings.DATABASE_URL)
        conn = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
        queue: asyncio.Queue = asyncio.Queue()

        def _enqueue(_conn, _pid, _channel, payload):
            queue.put_nowait(payload)

        await conn.add_listener(room_channel(display_name), _enqueue)
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {payload}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                await conn.remove_listener(room_channel(display_name), _enqueue)
            except Exception:
                pass
            await conn.close()

    return StreamingResponse(event_gen(), media_type="text/event-stream")
