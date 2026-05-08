# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Messages API — POST only.

After inserting a message, fires a Postgres NOTIFY on room:{room_name}
so SSE listeners receive it in real time.

Also hooks into the coordination service when the room is in 'negotiating' state.
"""

import asyncio
import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import notify, room_channel
from app.config import settings
from app.database import get_async_session
from app.models import CoordinationSession, Message, Room
from app.schemas import MessageCreate, MessageListResponse, MessageRead

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
    if not msg.message_type.startswith("coordination_") and msg.sender_handle != "CognitiveEngine":
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
):
    """List messages in a room (or coordination session), newest first."""
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

    query = query.order_by(Message.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    messages: list[Message] = list(result.scalars().all())

    return MessageListResponse(
        messages=[MessageRead.model_validate(m) for m in messages],
        total=len(messages),
    )
