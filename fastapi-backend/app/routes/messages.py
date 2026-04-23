# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

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
from app.models import Message, Room
from app.schemas import MessageCreate, MessageListResponse, MessageRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/messages", tags=["messages"])


async def _get_room_or_404(room_name: str, session: AsyncSession) -> Room:
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


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
    room = await _get_room_or_404(room_name, session)

    msg = Message(
        room_name=room_name,
        sender_handle=payload.sender_handle,
        recipient_handle=payload.recipient_handle,
        message_type=payload.message_type,
        content=payload.content,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)

    # Fire NOTIFY for SSE stream consumers
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
            await notify(
                conn,
                room_channel(room_name),
                {
                    "id": str(msg.id),
                    "room_name": room_name,
                    "sender_handle": msg.sender_handle,
                    "recipient_handle": msg.recipient_handle,
                    "message_type": msg.message_type,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                },
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"NOTIFY failed for room {room_name}: {e}")

    # Hook coordination service if this room is in negotiating state
    if room.coordination_state == "negotiating":
        from app.services import coordination

        asyncio.ensure_future(
            coordination.on_agent_response(room_name, msg.sender_handle, msg.content)
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
    """List messages in a room, newest first."""
    await _get_room_or_404(room_name, session)

    query = select(Message).where(Message.room_name == room_name)

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
