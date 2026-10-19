# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Pause or resume every agent a person owns, in one call.

POST /agents/pause and POST /agents/resume act on every agent whose manifest
names the caller as its owner, across rooms or in one (``room``), so stopping
for the night is one click. GET /agents/paused lists a person's paused agents,
for the status rail.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import AgentsControl, AgentsControlRead, PauseRead
from app.services import actor, agent_control, pauses
from app.services.agent_registry import norm_handle
from app.services.filesystem import room_exists

router = APIRouter(prefix="/agents", tags=["agents"])


def _owner(payload: AgentsControl, request: Request) -> str:
    owner = norm_handle(actor.bind_optional_actor(request, payload.by, field="by"))
    if not owner:
        raise HTTPException(status_code=422, detail="Say whose agents (`by`).")
    if payload.room and not room_exists(payload.room):
        raise HTTPException(status_code=404, detail="Room not found")
    return owner


@router.post("/pause", response_model=AgentsControlRead)
async def pause_mine(payload: AgentsControl, request: Request) -> AgentsControlRead:
    """Pause every agent the caller owns."""
    owner = _owner(payload, request)
    return AgentsControlRead(
        agents=[
            agent_control.pause(room, handle, owner)
            for room, handle in agent_control.owned_by(owner, payload.room)
        ]
    )


@router.post("/resume", response_model=AgentsControlRead)
async def resume_mine(payload: AgentsControl, request: Request) -> AgentsControlRead:
    """Resume every paused agent the caller owns."""
    owner = _owner(payload, request)
    return AgentsControlRead(
        agents=[
            agent_control.resume(room, handle, owner)
            for room, handle in agent_control.owned_by(owner, payload.room)
            if pauses.is_paused(room, handle)
        ]
    )


@router.get("/paused", response_model=list[PauseRead])
async def list_paused(
    request: Request, owner: str = Query(..., description="Whose agents")
) -> list[PauseRead]:
    """Every paused agent ``owner`` owns, across rooms.

    With sign-in on, only your own. With it off, anyone may list anyone's, as
    they may read any room's members.
    """
    who = norm_handle(actor.bind_optional_actor(request, owner, field="owner"))
    return agent_control.paused_of(who or "")
