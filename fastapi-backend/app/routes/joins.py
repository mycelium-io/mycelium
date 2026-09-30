# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""/rooms/{room}/joins and /joins/redeem: join codes for agents started elsewhere.

See ``services/joins.py``. Asking for a code takes the same right as acting as
the member it names (its owner, or someone its manifest allows), so a code can't
be used to become an agent you couldn't already speak for. Redeeming one takes
nothing but the code, which is why ``/joins/redeem`` is open when the gate is on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.schemas import JoinCreate, JoinRead, JoinRedeem, MembershipRead
from app.services import actor, member_tokens, principals
from app.services.agent_registry import norm_handle
from app.services.filesystem import room_exists
from app.services.joins import JoinError, joins

router = APIRouter(tags=["joins"])


def _when(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


@router.post("/rooms/{room_name}/joins", response_model=JoinRead, status_code=201)
def create_join(room_name: str, body: JoinCreate, request: Request) -> JoinRead:
    """A single-use code an agent redeems with ``mycelium join`` to become ``handle`` here."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    handle = norm_handle(body.handle)
    if not handle or principals.classify_sender(room_name, handle) != "agent":
        raise HTTPException(status_code=404, detail=f"@{body.handle} isn't an agent in {room_name}")
    actor.authorize_handle(request, room_name, handle)
    principal = actor.current_principal(request)
    code, join = joins.create(room_name, handle, created_by=principal.handle if principal else None)
    return JoinRead(code=code, room=room_name, handle=handle, expires_at=_when(join.expires_at))


@router.post("/joins/redeem", response_model=MembershipRead)
def redeem_join(body: JoinRedeem) -> MembershipRead:
    """Trade a join code for membership: the room, the handle, and a token when the hub needs one."""
    try:
        join = joins.redeem(body.code)
    except JoinError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not room_exists(join.room):
        raise HTTPException(status_code=404, detail=f"The room {join.room} no longer exists")
    token: str | None = None
    expires: datetime | None = None
    if settings.AUTH_ENABLED:
        token, expires_epoch = member_tokens.mint(join.handle, join.room)
        expires = _when(expires_epoch)
    return MembershipRead(room=join.room, handle=join.handle, token=token, token_expires_at=expires)
