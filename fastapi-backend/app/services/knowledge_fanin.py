# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Fire-and-forget fan-in to /api/knowledge/ingest.

The room write paths — channel messages and ``memory set`` — call into here
after their primary work commits. KXP forwards the content to CFN's shared
memories so the knowledge graph stays in sync with what's said and stored
in the room. Everything runs in-process: no HTTP self-call, no extra
serialisation hop, no risk of slow CFN forwards blocking the originating
request.

Records are formatted as otel-trace spans using the ioa_observe schema
(AGNTCY standard), matching what InsightClaw emits. When the sender is an
openclaw agent the record also includes ``openclaw.agent.input`` so backends
can correlate with InsightClaw traces.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import HTTPException

from app.database import async_session_maker

logger = logging.getLogger(__name__)

Source = Literal["channel_message", "memory_set", "context_file"]


def _build_otel_record(
    content: str,
    source: Source,
    sender_handle: str | None,
    agent_provider: str | None,
    output_text: str | None = None,
) -> dict[str, Any]:
    """Build a single otel-trace span record in the ioa_observe schema.

    When ``output_text`` is provided (e.g. for memory_set where the key is the
    prompt and the value is the stored result), input and output are split across
    ``entity.input`` and ``entity.output`` for natural prompt/completion semantics.
    """
    attrs: dict[str, Any] = {
        "ioa_observe.span.kind": "agent",
        "ioa_observe.entity.name": f"mycelium.{source}",
        "ioa_observe.entity.input": content,
    }
    if output_text is not None:
        attrs["ioa_observe.entity.output"] = output_text
    if sender_handle:
        attrs["gen_ai.agent.id"] = sender_handle
    if agent_provider == "openclaw":
        attrs["openclaw.agent.input"] = content

    return {
        "name": f"mycelium.{source}",
        "attributes": attrs,
        "resource": {"service.name": "mycelium"},
    }


async def fan_in(
    *,
    room_name: str,
    sender_handle: str | None,
    content: str,
    source: Source,
    agent_provider: str | None = None,
    output_text: str | None = None,
) -> None:
    """Forward a single room write to /api/knowledge/ingest.

    Designed to be wrapped in ``asyncio.ensure_future(...)`` so callers don't
    block. Failures are logged and swallowed — KXP is best-effort and
    must never break the underlying write.

    Args:
        agent_provider: Optional agent adapter type (e.g. ``"openclaw"``).
            When ``"openclaw"``, the span record includes ``openclaw.agent.input``
            so InsightClaw traces can be correlated. Pass ``None`` for cursor,
            hermes, CLI, or any unknown provider.
    """
    if not content:
        return

    # Defer the import to break a circular: knowledge.py imports services
    # for cache/buffer; importing it here at module load would create a
    # backref loop on app startup.
    from app.routes.knowledge import KnowledgeIngestRequest, knowledge_ingest

    payload = KnowledgeIngestRequest(
        records=[_build_otel_record(content, source, sender_handle, agent_provider, output_text)],
        agent_id=sender_handle,
        room_name=room_name,
        source=source,
        data_format="otel-trace",
    )

    try:
        async with async_session_maker() as db:
            await knowledge_ingest(payload, db=db)
    except HTTPException as exc:
        # Best-effort: an unresolvable target (most often a room with no MAS
        # of its own) is an expected skip, not an error. Logging it at WARNING
        # spammed a line on every channel message for such rooms.
        logger.debug(
            "KXP fan-in skipped | room=%s source=%s sender=%s detail=%s",
            room_name,
            source,
            sender_handle,
            getattr(exc, "detail", exc),
        )
    except Exception as exc:
        logger.warning(
            "KXP fan-in failed | room=%s source=%s sender=%s err=%s",
            room_name,
            source,
            sender_handle,
            exc,
        )
