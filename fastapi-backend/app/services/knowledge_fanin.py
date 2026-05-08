# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Fire-and-forget fan-in to /api/knowledge/ingest.

The room write paths — channel messages and ``memory set`` — call into here
after their primary work commits. KXP forwards the content to CFN's shared
memories so the knowledge graph stays in sync with what's said and stored
in the room. Everything runs in-process: no HTTP self-call, no extra
serialisation hop, no risk of slow CFN forwards blocking the originating
request.

Replaces the silent OpenClaw ``message:sent`` hook + Claude Code
``mycelium-stop.sh`` paths. Both shipped tool outputs and reasoning traces
without user awareness; the channel + memory_set paths only see what an
agent deliberately put into a room.
"""

from __future__ import annotations

import logging
from typing import Literal

from app.database import async_session_maker

logger = logging.getLogger(__name__)

Source = Literal["channel_message", "memory_set"]


async def fan_in(
    *,
    room_name: str,
    sender_handle: str | None,
    content: str,
    source: Source,
) -> None:
    """Forward a single room write to /api/knowledge/ingest.

    Designed to be wrapped in ``asyncio.ensure_future(...)`` so callers don't
    block. Failures are logged and swallowed — KXP is best-effort and
    must never break the underlying write.
    """
    if not content:
        return

    # Defer the import to break a circular: knowledge.py imports services
    # for cache/buffer; importing it here at module load would create a
    # backref loop on app startup.
    from app.routes.knowledge import KnowledgeIngestRequest, knowledge_ingest

    payload = KnowledgeIngestRequest(
        records=[{"content": content}],
        agent_id=sender_handle,
        room_name=room_name,
        source=source,
    )

    try:
        async with async_session_maker() as db:
            await knowledge_ingest(payload, db=db)
    except Exception as exc:
        logger.warning(
            "KXP fan-in failed | room=%s source=%s sender=%s err=%s",
            room_name,
            source,
            sender_handle,
            exc,
        )
