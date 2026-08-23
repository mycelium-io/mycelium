# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
SSE stream endpoints (DEPRECATED, fed by the in-process bus).

Minimal endpoints the UI still uses. Kept minimal on purpose — do not invest here.

GET /rooms/{room}/messages/stream — room event stream
GET /agents/{handle}/stream       — per-agent event stream
GET /events/stream                — global app events (room create/delete)
GET /notifications/stream         — aggregate: every room's activity, one stream
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.bus import agent_channel, app_channel, bus, room_channel
from app.services import in_memory_store
from app.services.filesystem import list_room_names, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


def _room_or_session_exists(name: str) -> bool:
    if room_exists(name):
        return True
    if ":session:" in name:
        parent, _, _short = name.partition(":session:")
        coord = in_memory_store.get_session(parent)
        return coord is not None and coord.display_name == name
    return False


async def _sse_from_channel(request: Request, channel: str):
    """Yield SSE frames from a bus channel until the client disconnects."""
    queue = bus.subscribe(channel)
    try:
        yield "event: ping\ndata: {}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(payload, default=str)}\n\n"
    finally:
        bus.unsubscribe(channel, queue)


@router.get("/rooms/{room_name}/messages/stream")
async def stream_room_messages(room_name: str, request: Request):
    """Server-Sent Events stream for a room."""
    if not _room_or_session_exists(room_name):
        raise HTTPException(status_code=404, detail=f"Room '{room_name}' not found")

    return StreamingResponse(
        _sse_from_channel(request, room_channel(room_name)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/agents/{handle}/stream")
async def stream_agent_events(handle: str, request: Request):
    """Server-Sent Events stream for a specific agent handle."""
    return StreamingResponse(
        _sse_from_channel(request, agent_channel(handle)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/events/stream")
async def stream_app_events(request: Request):
    """Server-Sent Events stream for global app state changes.

    Carries non-room-scoped events (``room_created`` / ``room_deleted``) so the
    UI's room list updates live without per-room polling.
    """
    return StreamingResponse(
        _sse_from_channel(request, app_channel()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _sse_notifications(request: Request):
    """Yield SSE frames merging the app channel with every room's channel.

    One subscription in place of the UI opening a per-room stream for every
    room the user participates in — the notification center's source feed.
    Frames are byte-identical to the per-room stream's (``l9_*``,
    ``coordination_join``, each carrying ``room_name``), plus
    the app channel's ``room_created``/``room_deleted``, which this generator
    also uses to grow/shrink its own room subscription set live.
    """
    app_queue = bus.subscribe(app_channel())
    room_queues: dict[str, asyncio.Queue] = {
        name: bus.subscribe(room_channel(name)) for name in list_room_names()
    }
    pending: set[asyncio.Task] = set()
    try:
        yield "event: ping\ndata: {}\n\n"
        while True:
            if await request.is_disconnected():
                break
            queues = [app_queue, *room_queues.values()]
            pending = {asyncio.ensure_future(q.get()) for q in queues}
            done, pending = await asyncio.wait(
                pending, timeout=15.0, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            pending = set()
            if not done:
                yield ": keep-alive\n\n"
                continue
            for task in done:
                payload = task.result()
                kind = payload.get("type")
                name = payload.get("room_name")
                if kind == "room_created" and isinstance(name, str) and name not in room_queues:
                    room_queues[name] = bus.subscribe(room_channel(name))
                elif kind == "room_deleted" and isinstance(name, str):
                    stale = room_queues.pop(name, None)
                    if stale is not None:
                        bus.unsubscribe(room_channel(name), stale)
                yield f"data: {json.dumps(payload, default=str)}\n\n"
    finally:
        for task in pending:
            task.cancel()
        bus.unsubscribe(app_channel(), app_queue)
        for name, q in room_queues.items():
            bus.unsubscribe(room_channel(name), q)


@router.get("/notifications/stream")
async def stream_notifications(request: Request):
    """Server-Sent Events stream aggregating activity across every room.

    Powers the notification center: a single connection, independent of which
    room (if any) is open, instead of the per-room stream that only carries
    activity for whatever room is currently on screen.
    """
    return StreamingResponse(
        _sse_notifications(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
