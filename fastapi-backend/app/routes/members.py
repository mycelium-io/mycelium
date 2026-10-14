# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
A room's members, from records (``app/services/room_people.py``).

GET    /rooms/{room}/members            — people, agents, engines and others
POST   /rooms/{room}/members            — add a person
DELETE /rooms/{room}/members/{handle}   — take a person out

People are recorded when they join; agents and engines are their manifests.
Who is *present* right now is ``/rooms/{room}/sessions/members``, a different
question.
"""

from fastapi import APIRouter, HTTPException, Request

from app.schemas import RoomMembers, RoomPerson, RoomPersonAdd
from app.services import actor, room_people
from app.services.agent_registry import norm_handle
from app.services.filesystem import read_room_meta, room_exists, write_room_meta

router = APIRouter(prefix="/rooms/{room_name}/members", tags=["members"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _refuse_unless(request: Request, room_name: str, allowed: set[str], what: str) -> None:
    """On a gated hub, only the handles in ``allowed`` (and the room's owner) may ``what``."""
    principal = actor.current_principal(request)
    if principal is None:
        return
    owner = norm_handle((read_room_meta(room_name) or {}).get("owner"))
    if norm_handle(principal.handle) in allowed | {owner} - {None}:
        return
    raise HTTPException(status_code=403, detail=f"@{principal.handle} can't {what}")


@router.get("", response_model=RoomMembers)
async def list_members(room_name: str) -> RoomMembers:
    """Everyone in the room, from records rather than from who has posted."""
    _require_room(room_name)
    return RoomMembers.model_validate(room_people.roster(room_name))


@router.post("", response_model=RoomPerson, status_code=201)
async def add_person(room_name: str, body: RoomPersonAdd, request: Request) -> RoomPerson:
    """Add a person to the room. They need a user record and can't be an agent here.

    On a gated hub the caller must be one of the room's people (or its owner).
    Adding someone already in the room returns their entry unchanged.
    """
    _require_room(room_name)
    handle = norm_handle(body.handle)
    if not handle or not room_people.can_be_person(room_name, handle):
        raise HTTPException(
            status_code=422,
            detail=f"@{body.handle} isn't a person: no user record, or an agent in {room_name}",
        )
    _refuse_unless(request, room_name, room_people.handles(room_name), "add people to this room")
    room_people.add(room_name, handle, "added")
    entry = next(p for p in room_people.people(room_name) if p["handle"] == handle)
    return RoomPerson.model_validate(entry)


@router.delete("/{handle}", status_code=204)
async def remove_person(room_name: str, handle: str, request: Request) -> None:
    """Take a person out of the room. On a gated hub, yourself or, as its owner, anyone."""
    _require_room(room_name)
    target = norm_handle(handle)
    if not target:
        raise HTTPException(status_code=404, detail=f"@{handle} isn't one of this room's people")
    _refuse_unless(request, room_name, {target}, f"remove @{handle} from this room")
    if not room_people.remove(room_name, target):
        raise HTTPException(status_code=404, detail=f"@{handle} isn't one of this room's people")
    # Someone taken out of a private room no longer has it listed either.
    meta = read_room_meta(room_name)
    if meta and target in (meta.get("members") or []):
        stored = {k: v for k, v in meta.items() if k != "id"}
        stored["members"] = [m for m in stored["members"] if m != target]
        write_room_meta(room_name, stored)
