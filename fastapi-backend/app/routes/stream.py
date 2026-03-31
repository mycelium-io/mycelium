# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
SSE stream endpoint — GET /rooms/{room}/messages/stream

Opens a raw asyncpg connection and LISTENs on `room:{room_name}`.
Each NOTIFY payload is forwarded as an SSE `data:` event.
Cleans up listener on client disconnect.
"""

import asyncio
import json
import logging
from urllib.parse import urlparse

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.bus import agent_channel, room_channel
from app.config import settings
from app.database import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


async def _expand_slim(payload: dict) -> dict:
    """Fetch the full message from DB if the NOTIFY payload was truncated."""
    from uuid import UUID

    from app.models import Message

    msg_id = payload.get("id")
    if not msg_id:
        return payload
    try:
        async for session in get_async_session():
            result = await session.execute(
                select(Message).where(Message.id == UUID(str(msg_id)))
            )
            msg = result.scalar_one_or_none()
            if msg:
                return {
                    "id": str(msg.id),
                    "room_name": msg.room_name,
                    "sender_handle": msg.sender_handle,
                    "recipient_handle": msg.recipient_handle,
                    "message_type": msg.message_type,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                }
    except Exception as e:
        logger.warning("Failed to expand slim NOTIFY payload %s: %s", msg_id, e)
    return payload


@router.get("/rooms/{room_name}/messages/stream")
async def stream_room_messages(room_name: str, request: Request):
    """
    Server-Sent Events stream for a room.

    Yields SSE events as messages arrive via Postgres NOTIFY.
    Connect with: curl -N http://localhost:8000/rooms/{room}/messages/stream
    """
    parsed = urlparse(settings.DATABASE_URL)

    try:
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}") from e

    channel = room_channel(room_name)
    queue: asyncio.Queue = asyncio.Queue()

    def _on_notify(
        _conn: asyncpg.Connection,
        _pid: int,
        _channel: str,
        payload: str,
    ) -> None:
        queue.put_nowait(payload)

    await conn.add_listener(channel, _on_notify)
    await conn.execute(f'LISTEN "{channel}"')
    logger.debug(f"SSE stream opened for room: {room_name}")

    async def event_generator():
        try:
            # Send an initial ping so the client knows the stream is live
            yield "event: ping\ndata: {}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if data.get("_slim"):
                        data = await _expand_slim(data)
                    yield f"data: {json.dumps(data)}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            try:
                await conn.execute(f'UNLISTEN "{channel}"')
                await conn.remove_listener(channel, _on_notify)
                await conn.close()
            except Exception:
                pass
            logger.debug(f"SSE stream closed for room: {room_name}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/agents/{handle}/stream")
async def stream_agent_events(handle: str, request: Request):
    """
    Server-Sent Events stream for a specific agent handle.

    Delivers coordination_tick and coordination_consensus events addressed to
    this agent across all rooms — no room configuration required on the client.
    Connect with: curl -N http://localhost:8000/agents/{handle}/stream
    """
    parsed = urlparse(settings.DATABASE_URL)

    try:
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}") from e

    channel = agent_channel(handle)
    queue: asyncio.Queue = asyncio.Queue()

    def _on_notify(
        _conn: asyncpg.Connection,
        _pid: int,
        _channel: str,
        payload: str,
    ) -> None:
        queue.put_nowait(payload)

    await conn.add_listener(channel, _on_notify)
    await conn.execute(f'LISTEN "{channel}"')
    logger.debug(f"SSE agent stream opened for: {handle}")

    async def event_generator():
        try:
            yield "event: ping\ndata: {}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    try:
                        json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    yield f"data: {payload}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            try:
                await conn.execute(f'UNLISTEN "{channel}"')
                await conn.remove_listener(channel, _on_notify)
                await conn.close()
            except Exception:
                pass
            logger.debug(f"SSE agent stream closed for: {handle}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
