# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
SSE stream endpoints (DEPRECATED — retired in Step 10).

Formerly backed by Postgres LISTEN/NOTIFY; now fed by the in-process bus
(SLIM-native rebuild, Step 1). The UI still uses SSE until the coordination bus
moves to SLIM (Steps 3-4) and the UI is reworked (Step 10). Kept minimal on
purpose — do not invest here.

GET /rooms/{room}/messages/stream — room event stream
GET /agents/{handle}/stream       — per-agent event stream
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.bus import agent_channel, bus, room_channel
from app.services import local_state
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


def _room_or_session_exists(name: str) -> bool:
    if room_exists(name):
        return True
    if ":session:" in name:
        parent, _, _short = name.partition(":session:")
        coord = local_state.get_session(parent)
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
