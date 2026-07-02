# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Messages API — POST only.

After inserting a message, fires a Postgres NOTIFY on room:{room_name}
so SSE listeners receive it in real time.

Also hooks into the coordination service when the room is in 'negotiating' state.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import notify, room_channel
from app.config import settings
from app.database import get_async_session
from app.models import CoordinationSession, Message, Room
from app.schemas import (
    STATEFUL_EVENT_KINDS,
    EventStatusUpdate,
    MessageCreate,
    MessageListResponse,
    MessageRead,
    MessageType,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/messages", tags=["messages"])


async def _resolve_target(
    name: str, session: AsyncSession
) -> tuple[Room | None, CoordinationSession | None]:
    """Resolve a path name to either a real Room or a CoordinationSession.

    Names with the legacy ``{parent}:session:{short}`` shape resolve to a
    coordination session — there is no Room row for them. Real room names
    resolve to the Room. 404 if neither matches.
    """
    if ":session:" in name:
        parent, _, short_id = name.partition(":session:")
        result = await session.execute(
            select(CoordinationSession).where(
                CoordinationSession.parent_room_name == parent,
                CoordinationSession.short_id == short_id,
            )
        )
        coord = result.scalar_one_or_none()
        if coord:
            return None, coord

    result = await session.execute(select(Room).where(Room.name == name))
    room = result.scalar_one_or_none()
    if room:
        return room, None

    raise HTTPException(status_code=404, detail="Room or session not found")


@router.post("", response_model=MessageRead, status_code=201)
async def send_message(
    room_name: str,
    payload: MessageCreate,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Send a message to a room.

    After persisting, fires NOTIFY on `room:{room_name}` so SSE subscribers
    receive it without polling.
    """
    room, coord = await _resolve_target(room_name, session)

    msg = Message(
        room_name=room.name if room else None,
        coordination_session_id=coord.id if coord else None,
        sender_handle=payload.sender_handle,
        recipient_handle=payload.recipient_handle,
        message_type=payload.message_type,
        content=payload.content,
    )
    if payload.metadata is not None:
        # Promote kind/status to indexed columns and precompute expiry so the
        # feed/ledger filters and the TTL sweep never touch JSON paths.
        meta = payload.metadata.model_dump(exclude_none=True)
        msg.event_metadata = meta
        msg.event_kind = payload.metadata.kind
        msg.event_status = payload.metadata.status
        if payload.metadata.ttl_seconds:
            msg.event_expires_at = datetime.now(UTC) + timedelta(
                seconds=payload.metadata.ttl_seconds
            )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)

    # _resolve_target raises 404 if neither, so exactly one is non-None.
    notify_payload: dict = {
        "id": str(msg.id),
        "sender_handle": msg.sender_handle,
        "recipient_handle": msg.recipient_handle,
        "message_type": msg.message_type,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
    }
    if msg.event_metadata is not None:
        notify_payload["metadata"] = msg.event_metadata
    if room is not None:
        notify_channel = room_channel(room.name)
        notify_payload["room_name"] = room.name
    elif coord is not None:
        notify_channel = room_channel(coord.display_name)
        notify_payload["coordination_session_id"] = str(coord.id)
        notify_payload["room_name"] = coord.display_name  # legacy compat
    else:
        raise HTTPException(status_code=500, detail="resolver returned (None, None)")
    try:
        from urllib.parse import urlparse

        parsed = urlparse(settings.DATABASE_URL)
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
        try:
            await notify(conn, notify_channel, notify_payload)
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("NOTIFY failed for %s: %s", notify_channel, e)

    if coord and coord.state == "negotiating":
        from app.services import coordination

        asyncio.ensure_future(
            coordination.on_agent_response(coord.display_name, msg.sender_handle, msg.content)
        )

    # Fan in to KXP. Skip system-emitted coordination chatter (those are
    # CognitiveEngine-authored; ingesting them would loop the KG on its own
    # mediator output). Only deliberate agent speech reaches CFN.
    if (
        not msg.message_type.startswith("coordination_")
        and msg.message_type != MessageType.EVENT
        and msg.sender_handle != "CognitiveEngine"
    ):
        from app.services.knowledge_fanin import fan_in

        target_room = room.name if room is not None else (coord.display_name if coord else None)
        if target_room:
            asyncio.ensure_future(
                fan_in(
                    room_name=target_room,
                    sender_handle=msg.sender_handle,
                    content=msg.content,
                    source="channel_message",
                )
            )

    return msg


@router.get("", response_model=MessageListResponse)
async def list_messages(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
    limit: int = Query(50, le=500),
    offset: int = 0,
    sender: str | None = None,
    message_type: str | None = None,
    kind: str | None = Query(None, description="Filter events by metadata.kind"),
    status: str | None = Query(None, description="Filter events by ledger status"),
    since: datetime | None = Query(None, description="Only messages created at/after this time"),
):
    """List messages in a room (or coordination session), newest first.

    ``kind``/``status``/``since`` make the source-activity feed and the
    action/concern ledger server-side filters over the room (#392). Expired
    events (past their ``ttl_seconds``) are excluded even if the sweep
    hasn't collected them yet.
    """
    room, coord = await _resolve_target(room_name, session)

    if room is not None:
        query = select(Message).where(Message.room_name == room.name)
    else:
        assert coord is not None
        # Surface both new (coord_session_id) and legacy (display-name room_name) rows.
        query = select(Message).where(
            (Message.coordination_session_id == coord.id)
            | (Message.room_name == coord.display_name)
        )

    if sender:
        query = query.where(Message.sender_handle == sender)
    if message_type:
        query = query.where(Message.message_type == message_type)
    if kind:
        query = query.where(Message.event_kind == kind)
    if status:
        query = query.where(Message.event_status == status)
    if since:
        query = query.where(Message.created_at >= since)
    # Hide expired-but-unswept events.
    query = query.where(
        (Message.event_expires_at.is_(None)) | (Message.event_expires_at > datetime.now(UTC))
    )

    query = query.order_by(Message.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    messages: list[Message] = list(result.scalars().all())

    return MessageListResponse(
        messages=[MessageRead.model_validate(m) for m in messages],
        total=len(messages),
    )


@router.patch("/{message_id}", response_model=MessageRead)
async def update_event_status(
    room_name: str,
    message_id: UUID,
    payload: EventStatusUpdate,
    session: AsyncSession = Depends(get_async_session),
):
    """Transition a stateful event's status (open -> in_progress -> resolved).

    Design choice (#392 left it open): the status lives on the original event
    row and is updated in place, rather than appending follow-up events —
    the current status must be cheaply queryable, and a follow-up-event model
    forces a latest-per-correlation aggregation on every ledger query. The
    transition is broadcast over SSE so subscribers see the change live.
    """
    room, coord = await _resolve_target(room_name, session)

    result = await session.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    in_target = msg is not None and (
        (room is not None and msg.room_name == room.name)
        or (coord is not None and msg.coordination_session_id == coord.id)
    )
    if msg is None or not in_target:
        raise HTTPException(status_code=404, detail="Message not found in this room")
    if msg.message_type != MessageType.EVENT or not msg.event_kind:
        raise HTTPException(status_code=409, detail="Not an event message")
    if msg.event_kind not in STATEFUL_EVENT_KINDS and msg.event_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Event kind {msg.event_kind!r} is stateless — no status to transition",
        )

    msg.event_status = payload.status
    # Keep the returned metadata consistent with the promoted column.
    meta = dict(msg.event_metadata or {})
    meta["status"] = payload.status
    meta["status_updated_at"] = datetime.now(UTC).isoformat()
    msg.event_metadata = meta
    await session.commit()
    await session.refresh(msg)

    notify_payload = {
        "id": str(msg.id),
        "sender_handle": msg.sender_handle,
        "recipient_handle": msg.recipient_handle,
        "message_type": msg.message_type,
        "content": msg.content,
        "metadata": msg.event_metadata,
        "created_at": msg.created_at.isoformat(),
        "status_transition": payload.status,
    }
    channel_name = room.name if room is not None else coord.display_name  # type: ignore[union-attr]
    notify_payload["room_name"] = channel_name
    try:
        from urllib.parse import urlparse

        parsed = urlparse(settings.DATABASE_URL)
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
        try:
            await notify(conn, room_channel(channel_name), notify_payload)
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("NOTIFY failed for %s: %s", channel_name, e)

    return msg
