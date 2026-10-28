# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Verifier API — the lines it adds under messages, and its settings.

See ``app/services/verifier.py``. The verifier is turned on for the hub in its
config (``verifier.enabled``) and added to a room like any engine; these routes
read what it found and let a person answer it.

GET  /rooms/{room}/verifier/flags                 — the room's flags (``?since=``)
POST /rooms/{room}/verifier/flags/{flag_id}/fine  — someone says a flag is fine
GET  /verifier/settings                           — what the settings section shows
POST /verifier/learn                              — start learning from the rooms it checks
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import VerifierFineRequest, VerifierFlagRead, VerifierSettingsRead, refusals
from app.services import actor, verifier
from app.services.filesystem import room_exists

router = APIRouter(tags=["verifier"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


@router.get(
    "/rooms/{room_name}/verifier/flags",
    response_model=list[VerifierFlagRead],
    responses=refusals(404),
)
async def list_flags(
    room_name: str,
    since: datetime | None = Query(None, description="Only flags raised at or after this time"),
) -> list[VerifierFlagRead]:
    """The room's flags, oldest first: shown ones and ones someone said are fine."""
    _require_room(room_name)
    return [VerifierFlagRead.model_validate(f) for f in verifier.flags_since(room_name, since)]


@router.post(
    "/rooms/{room_name}/verifier/flags/{flag_id}/fine",
    response_model=VerifierFlagRead,
    responses=refusals(403, 404),
)
async def mark_fine(
    room_name: str, flag_id: str, payload: VerifierFineRequest, request: Request
) -> VerifierFlagRead:
    """Someone says the claim is fine: the line goes away for everyone, and the
    answer is kept for the verifier to learn from."""
    _require_room(room_name)
    by = actor.bind_optional_actor(request, payload.by, field="by") or "someone"
    flag = await request.app.state.verifier.mark_fine(room_name, flag_id, by)
    if flag is None:
        raise HTTPException(status_code=404, detail="No such flag in this room")
    return VerifierFlagRead.model_validate(flag)


@router.get("/verifier/settings", response_model=VerifierSettingsRead)
async def get_settings(request: Request) -> VerifierSettingsRead:
    """On or off, the rooms it checks, which model it's using, and Learn's state."""
    view = await asyncio.to_thread(request.app.state.verifier.settings_view)
    return VerifierSettingsRead.model_validate(view)


@router.post(
    "/verifier/learn",
    response_model=VerifierSettingsRead,
    status_code=202,
    responses=refusals(403, 409),
)
async def start_learn(request: Request) -> VerifierSettingsRead:
    """Label the past messages of the rooms it checks with the hub's model, once,
    then fit the claim spotter to them. Runs in the background; poll the settings.

    It spends the hub's model budget, so with sign-in on only a person may start
    it, never an agent's token."""
    principal = actor.current_principal(request)
    if principal is not None and principal.role != "user":
        raise HTTPException(status_code=403, detail="Only a person can start Learn")
    engine = request.app.state.verifier
    if not engine.rooms():
        raise HTTPException(status_code=409, detail="No room has added the verifier yet")
    if not engine.start_learn():
        raise HTTPException(status_code=409, detail="Learning is already running")
    return VerifierSettingsRead.model_validate(await asyncio.to_thread(engine.settings_view))
