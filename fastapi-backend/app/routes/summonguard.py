# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""GET /rooms/{room_name}/summonguard — what the room's summon guard decided.

A suppressed wake is, by design, invisible: the agent simply never gets a turn.
That is fine when the guard is right and baffling when it is wrong, so the
decisions are readable — whether a guard is installed at all, which engine
installed it, and the recent verdicts with the classifier's own one-line reason.

Read-only and in-memory: the window is the last few decisions per room, not an
audit log. The transcript remains the durable record of what was said.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import summon_filter
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/summonguard", tags=["engines"])


class SummonVerdictRead(BaseModel):
    """One message's summon decisions."""

    message_id: str
    sender: str
    text: str
    decisions: dict[str, str] = Field(..., description="handle -> 'wake' | 'mention'")
    reasons: dict[str, str] = Field(default_factory=dict)
    source: str = Field(..., description="How it was decided: pi | leading-mention | fail-open | …")
    decided_at: str


class SummonGuardStatus(BaseModel):
    """Whether a room's summons are guarded, and what the guard has been deciding."""

    room: str
    installed: bool = Field(..., description="True when a summon filter is installed.")
    guards: list[str] = Field(default_factory=list, description="Engines that installed it.")
    disabled: bool = Field(..., description="Kill switch: guards classify everything as a wake.")
    verdicts: list[SummonVerdictRead] = Field(default_factory=list)


@router.get("", response_model=SummonGuardStatus)
async def summonguard_status(
    room_name: str, limit: int = Query(20, ge=1, le=100)
) -> SummonGuardStatus:
    """The room's guard status plus its most recent verdicts, newest first."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    from app.config import settings

    return SummonGuardStatus(
        room=room_name,
        installed=summon_filter.guarded(room_name),
        guards=summon_filter.owners(room_name),
        disabled=settings.SUMMONGUARD_DISABLE,
        verdicts=[
            SummonVerdictRead(
                message_id=v.message_id,
                sender=v.sender,
                text=v.text,
                decisions=v.decisions,
                reasons=v.reasons,
                source=v.source,
                decided_at=v.decided_at,
            )
            for v in summon_filter.verdicts.recent(room_name, limit=limit)
        ],
    )
