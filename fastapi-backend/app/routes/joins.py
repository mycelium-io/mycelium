# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""/rooms/{room}/joins, /invites and /joins/redeem: join codes for agents started elsewhere.

See ``services/joins.py``. Asking for a code takes the same right as acting as
the member it names (its owner, or someone its manifest allows), so a code can't
be used to become an agent you couldn't already speak for. An invite is the
same code for an agent that may not exist yet: it is added to the room first,
owned by whoever asked. Redeeming one takes nothing but the code, which is why
``/joins/redeem`` is open when the gate is on.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.schemas import (
    HANDLE_PATTERN,
    InviteCreate,
    JoinCreate,
    JoinRead,
    JoinRedeem,
    MembershipRead,
    refusals,
)
from app.services import actor, member_tokens, principals
from app.services.agent_registry import norm_handle, write_agent_manifest
from app.services.auth import GATE_REFUSALS
from app.services.filesystem import room_exists
from app.services.joins import CODE_TTL_S, JoinError, joins

router = APIRouter(tags=["joins"])


def _when(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


@router.post(
    "/rooms/{room_name}/joins",
    response_model=JoinRead,
    status_code=201,
    responses={**GATE_REFUSALS, **refusals(403, 404)},
)
def create_join(room_name: str, body: JoinCreate, request: Request) -> JoinRead:
    """A single-use code an agent redeems with ``mycelium join`` to become ``handle`` here."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    handle = norm_handle(body.handle)
    if not handle or principals.classify_sender(room_name, handle) != "agent":
        raise HTTPException(status_code=404, detail=f"@{body.handle} isn't an agent in {room_name}")
    actor.authorize_handle(request, room_name, handle)
    principal = actor.current_principal(request)
    code, join = joins.create(
        room_name,
        handle,
        created_by=principal.handle if principal else None,
        ttl_s=body.ttl_minutes * 60 if body.ttl_minutes else CODE_TTL_S,
    )
    return JoinRead(code=code, room=room_name, handle=handle, expires_at=_when(join.expires_at))


_HANDLE_RE = re.compile(HANDLE_PATTERN)
#: What an invited agent is recorded as running: a session somewhere else,
#: started by someone, that joined with a code.
INVITED_FRAMEWORK = "external"


@router.post(
    "/rooms/{room_name}/invites",
    response_model=JoinRead,
    status_code=201,
    responses={**GATE_REFUSALS, **refusals(403, 404, 409, 422)},
)
async def create_invite(room_name: str, body: InviteCreate, request: Request) -> JoinRead:
    """A join code for ``handle``, adding it to the room first if it's new.

    What the app's Open session and ``mycelium agent invite`` hand to an agent
    running anywhere: it redeems the code with ``mycelium join`` and is that
    member. A handle that is a person, or an engine, gets no code.
    """
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    handle = norm_handle(body.handle)
    if not handle or not _HANDLE_RE.match(handle):
        raise HTTPException(
            status_code=422,
            detail="Handle must be a lowercase slug (a-z, 0-9, '-', '_') starting alphanumeric.",
        )
    kind = principals.classify_sender(room_name, handle)
    if kind in ("user", "engine"):
        what = "a person" if kind == "user" else "an engine"
        raise HTTPException(status_code=409, detail=f"@{handle} is {what}. Pick another handle.")
    me = actor.bind_optional_actor(request, body.created_by, field="created_by")
    if kind == "unknown":
        # An invited session runs somewhere we can't see, so it's recorded as
        # external.
        manifest: dict[str, object] = {
            "adapter": "claude_code",
            "framework": INVITED_FRAMEWORK,
            "description": body.description,
        }
        if me:
            manifest["owner"] = me
        await write_agent_manifest(
            room_name,
            handle,
            manifest,
            created_by=me or "web-ui",
            principal=actor.principal_handle(request),
        )
    actor.authorize_handle(request, room_name, handle)
    code, join = joins.create(
        room_name,
        handle,
        created_by=me,
        ttl_s=body.ttl_minutes * 60 if body.ttl_minutes else CODE_TTL_S,
    )
    return JoinRead(code=code, room=room_name, handle=handle, expires_at=_when(join.expires_at))


@router.post("/joins/redeem", response_model=MembershipRead, responses=refusals(400, 404))
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
