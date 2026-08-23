# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Agent context — what a room tells an agent on arrival.

GET /rooms/{room}/agent-context — compact briefing for an agent's prompt

A room-scoped resource rather than a sub-path of anything: it is the single
endpoint every dispatch path hits to learn what the room is for.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import briefing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}", tags=["briefing"])


class AgentContextOut(BaseModel):
    room: str
    handle: str | None = None
    generated_at: str  # ISO-8601 UTC — callers render staleness from this
    context: str | None = None  # None when the room has nothing to brief on


@router.get("/agent-context", response_model=AgentContextOut)
async def get_agent_context(room_name: str, handle: str | None = None) -> AgentContextOut:
    """Compact room briefing injected into an agent's prompt on dispatch.

    Hot path — called on every ``@handle`` dispatch — so it stays a pure
    filesystem read. ``handle`` is accepted and reserved for per-agent framing
    (what *you* are holding) once that lands; today it returns the room-wide
    briefing regardless.
    """
    return AgentContextOut(
        room=room_name,
        handle=handle,
        generated_at=datetime.now(UTC).isoformat(),
        context=briefing.agent_context(room_name),
    )
