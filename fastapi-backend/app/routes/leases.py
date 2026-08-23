# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Custody API — who holds a row, and for how much longer.

GET  /rooms/{room}/leases/{key}        — one row's custody, right now
POST /rooms/{room}/leases/claim        — take custody, for a window
POST /rooms/{room}/leases/release      — hand it back, with a signed note
POST /rooms/{room}/leases/resolve      — the work is done; the row leaves
POST /rooms/{room}/leases/renew        — a resident loop's heartbeat
GET  /rooms/{room}/leases/await        — wake on this lease's transitions

A sibling router rather than routes under ``/memory``: the memory router ends in
a ``{key:path}`` catch-all, so a suffix hung off it is an ordering bug waiting to
happen (the same reason ``links`` sits beside it).

The one endpoint worth reading twice is ``await``.  It watches a lease rather
than the room's channel, because waking on channel traffic to monitor a handoff
is the wrong subscription: a dozen unrelated messages wake you for nothing.  A
lease is already a state machine whose transitions are exactly what a handoff
cares about — claimed, lapsed, released, resolved — so it is the subscription
object, and no message can wake it.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services import actor, leases
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/leases", tags=["leases"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _fail(error: leases.LeaseError) -> HTTPException:
    return HTTPException(
        status_code=error.status, detail={"error": "lease", "message": error.reason, **error.detail}
    )


class ClaimBody(BaseModel):
    key: str = Field(..., description="Memory key of the work/ row being claimed")
    handle: str = Field(..., description="The handle taking custody")
    ttl_minutes: int = Field(
        leases.DEFAULT_TTL_MINUTES,
        ge=1,
        description="Minutes the claim holds without a renewal before it drains",
    )


class ReleaseBody(BaseModel):
    key: str = Field(..., description="Memory key of the row being handed back")
    handle: str = Field(..., description="The handle releasing it")
    note: str | None = Field(None, description="Why — recorded against the releaser's name")


class ResolveBody(BaseModel):
    key: str = Field(..., description="Memory key of the row being resolved")
    handle: str = Field(..., description="The handle resolving it")


class RenewBody(BaseModel):
    handle: str = Field(..., description="The resident handle whose claims are being renewed")


@router.post("/claim")
async def claim_lease(room_name: str, body: ClaimBody, request: Request):
    """Take custody of a row for a window, not for good."""
    _require_room(room_name)
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
    try:
        return await leases.claim(room_name, body.key, handle, body.ttl_minutes, datetime.now(UTC))
    except leases.LeaseError as e:
        raise _fail(e) from e


@router.post("/release")
async def release_lease(room_name: str, body: ReleaseBody, request: Request):
    """Hand a row back on purpose, and sign the note that says so."""
    _require_room(room_name)
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
    try:
        return await leases.release(room_name, body.key, handle, body.note, datetime.now(UTC))
    except leases.LeaseError as e:
        raise _fail(e) from e


@router.post("/resolve")
async def resolve_lease(room_name: str, body: ResolveBody, request: Request):
    """The work is done: the row leaves the board rather than draining out of it."""
    _require_room(room_name)
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
    try:
        return await leases.resolve(room_name, body.key, handle, datetime.now(UTC))
    except leases.LeaseError as e:
        raise _fail(e) from e


@router.post("/renew")
async def renew_leases(room_name: str, body: RenewBody, request: Request):
    """A resident loop saying it is still here, on behalf of every row it holds.

    Quiet by design: a lease still in its first half is left alone, and the
    writes this does make broadcast nothing.
    """
    _require_room(room_name)
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
    renewed = await leases.renew(room_name, handle, datetime.now(UTC))
    return {"room": room_name, "handle": handle.lstrip("@"), "renewed": renewed}


@router.get("/await")
async def await_lease(
    room_name: str,
    key: str = Query(..., description="Memory key of the lease to watch"),
    since: str | None = Query(
        None,
        description=(
            "The `since` token from a previous call. Omit for orientation: the "
            "current state comes straight back rather than blocking."
        ),
    ),
    timeout: int = Query(0, ge=0, le=leases.MAX_WAIT_S, description="Seconds to hold the request"),
):
    """Wake on this lease's transitions, and on nothing else."""
    _require_room(room_name)
    try:
        return await leases.watch(room_name, key, since, timeout)
    except leases.LeaseError as e:
        raise _fail(e) from e


@router.get("/{key:path}")
async def read_lease(room_name: str, key: str):
    """One row's custody as it stands, including a drain nobody wrote down."""
    _require_room(room_name)
    try:
        return leases.read(room_name, key, datetime.now(UTC))
    except leases.LeaseError as e:
        raise _fail(e) from e
