# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

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
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.bus import agent_channel, room_channel
from app.config import settings
from app.database import async_session_maker
from app.models import CoordinationSession, Room

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
        async with async_session_maker() as session:
            result = await session.execute(select(Message).where(Message.id == UUID(str(msg_id))))
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


async def _open_listen_conn() -> asyncpg.Connection:
    """Open a raw asyncpg connection for LISTEN/NOTIFY use.

    Each SSE stream gets its own dedicated connection because asyncpg's
    LISTEN occupies the connection for the lifetime of the subscription.
    Caller is responsible for closing the connection — see _close_listen_conn.
    """
    parsed = urlparse(settings.DATABASE_URL)
    return await asyncpg.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip("/"),
    )


async def _close_listen_conn(
    conn: asyncpg.Connection | None,
    channel: str,
    callback,
) -> None:
    """Best-effort UNLISTEN + remove_listener + close. Never raises."""
    if conn is None:
        return
    # Each step is independently guarded so a failure in one (e.g. the
    # connection is already half-closed) doesn't block the others.
    try:
        if not conn.is_closed():
            await conn.execute(f'UNLISTEN "{channel}"')
    except Exception as e:
        logger.debug(f"SSE cleanup: UNLISTEN {channel} failed: {e}")
    try:
        conn.remove_listener(channel, callback)
    except Exception as e:
        logger.debug(f"SSE cleanup: remove_listener {channel} failed: {e}")
    try:
        if not conn.is_closed():
            await conn.close()
    except Exception as e:
        logger.debug(f"SSE cleanup: close failed for {channel}: {e}")


async def _stream_with_disconnect_watcher(
    request: Request,
    queue: asyncio.Queue,
    transform,
):
    """SSE generator that races queue.get() against client-disconnect.

    The original implementation only checked `request.is_disconnected()` once
    every 15 seconds (between blocking queue gets), so a hung-up client could
    leave the LISTEN connection pinned to Postgres for arbitrary durations.
    The connection leak compounded across tests because each leaked LISTEN
    holds a dedicated connection; we hit max_connections after a few dozen
    test rooms.

    The fix: spawn a watcher task that resolves when the client disconnects,
    and `wait(..., FIRST_COMPLETED)` between it and the queue. The first one
    to finish wakes us up; if it's the watcher, we exit and the surrounding
    generator's `finally` runs cleanup immediately.
    """

    async def _watch_disconnect():
        # Poll roughly twice per second — Starlette's receive channel is the
        # only signal we have. is_disconnected() is cheap.
        while True:
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.5)

    yield "event: ping\ndata: {}\n\n"

    disconnect_task = asyncio.create_task(_watch_disconnect())
    try:
        while True:
            get_task = asyncio.create_task(queue.get())
            try:
                done, _ = await asyncio.wait(
                    {get_task, disconnect_task},
                    timeout=15.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError:
                get_task.cancel()
                raise

            if disconnect_task in done:
                get_task.cancel()
                break

            if not done:
                # Timeout — emit keep-alive and loop. The keep-alive write is
                # also our other disconnect signal: if the client is gone the
                # write will fail and StreamingResponse will cancel us.
                get_task.cancel()
                yield ": keep-alive\n\n"
                continue

            # queue.get() completed
            payload = get_task.result()
            line = await transform(payload)
            if line is not None:
                yield line
    finally:
        disconnect_task.cancel()


@router.get("/rooms/{room_name}/messages/stream")
async def stream_room_messages(room_name: str, request: Request):
    """
    Server-Sent Events stream for a room.

    Yields SSE events as messages arrive via Postgres NOTIFY.
    Connect with: curl -N http://localhost:8000/rooms/{room}/messages/stream
    """
    async with async_session_maker() as db:
        room_result = await db.execute(select(Room).where(Room.name == room_name))
        if not room_result.scalar_one_or_none():
            # Also accept coordination session display names, which follow the
            # pattern "{parent_room_name}:session:{short_id}" but have no Room
            # table entry of their own.  display_name is a @property so we
            # parse the short_id from the tail of the URL segment instead.
            found = False
            if ":session:" in room_name:
                parent, _, short_id = room_name.partition(":session:")
                cs_result = await db.execute(
                    select(CoordinationSession).where(
                        CoordinationSession.parent_room_name == parent,
                        CoordinationSession.short_id == short_id,
                    )
                )
                found = cs_result.scalar_one_or_none() is not None
            if not found:
                raise HTTPException(status_code=404, detail=f"Room '{room_name}' not found")

    try:
        conn: asyncpg.Connection = await _open_listen_conn()
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

    listener_added = False
    try:
        await conn.add_listener(channel, _on_notify)
        listener_added = True
        await conn.execute(f'LISTEN "{channel}"')
    except Exception as e:
        # If subscription setup fails, release the connection immediately —
        # otherwise it leaks for the lifetime of the process.
        await _close_listen_conn(conn, channel, _on_notify if listener_added else None)
        raise HTTPException(status_code=503, detail=f"LISTEN setup failed: {e}") from e

    logger.debug(f"SSE stream opened for room: {room_name}")

    async def _transform(payload: str) -> str | None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if data.get("_slim"):
            data = await _expand_slim(data)
        return f"data: {json.dumps(data)}\n\n"

    async def event_generator():
        try:
            async for chunk in _stream_with_disconnect_watcher(request, queue, _transform):
                yield chunk
        except asyncio.CancelledError:
            pass
        finally:
            await _close_listen_conn(conn, channel, _on_notify)
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
async def stream_agent_events(
    handle: str,
    request: Request,
    room: list[str] = Query(default=[]),
):
    """
    Server-Sent Events stream for a specific agent handle.

    Delivers coordination_tick and coordination_consensus events addressed to
    this agent. Pass one or more ``?room=<name>`` query parameters to scope
    delivery to a specific session — only events whose ``room_name`` exactly
    matches one of the supplied values are forwarded. Without any ``room``
    parameter all events for the handle are delivered (legacy behaviour).

    Connect with: curl -N http://localhost:8000/agents/{handle}/stream
    Connect scoped: curl -N "http://localhost:8000/agents/{handle}/stream?room=my-room:session:abc123"
    """
    try:
        conn: asyncpg.Connection = await _open_listen_conn()
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

    listener_added = False
    try:
        await conn.add_listener(channel, _on_notify)
        listener_added = True
        await conn.execute(f'LISTEN "{channel}"')
    except Exception as e:
        await _close_listen_conn(conn, channel, _on_notify if listener_added else None)
        raise HTTPException(status_code=503, detail=f"LISTEN setup failed: {e}") from e

    logger.debug(f"SSE agent stream opened for: {handle} (room filter: {room or 'none'})")

    room_set: frozenset[str] = frozenset(room)

    async def _transform(payload: str) -> str | None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if room_set and (data.get("room_name") or "") not in room_set:
            return None
        return f"data: {payload}\n\n"

    async def event_generator():
        try:
            async for chunk in _stream_with_disconnect_watcher(request, queue, _transform):
                yield chunk
        except asyncio.CancelledError:
            pass
        finally:
            await _close_listen_conn(conn, channel, _on_notify)
            logger.debug(f"SSE agent stream closed for: {handle}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
