# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent's subagents in a room (``services/subagents.py``).

GET lists every subagent the room has had, ended ones too, so a message from
one still reads as its parent's after it's gone. POST starts one as its parent
(``mycelium subagent start``), and DELETE ends it (``mycelium subagent end``):
its parent, or anyone who may act as the parent, may do either.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas import SubagentCreate, SubagentRead, refusals
from app.services import actor, subagents
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/subagents", tags=["subagents"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _read(entry: dict) -> SubagentRead:
    return SubagentRead(
        handle=entry["handle"],
        parent=entry["parent"],
        name=entry["name"],
        state=entry.get("state", "working"),
        started_at=entry.get("started_at", ""),
        ended_at=entry.get("ended_at"),
        ended_by=entry.get("ended_by"),
    )


@router.get("", response_model=list[SubagentRead], responses=refusals(404))
async def list_subagents(room_name: str) -> list[SubagentRead]:
    """Every subagent the room has had, oldest first, ended ones included.
    One that ran out of time since the last read hands back what it held."""
    _require_room(room_name)
    found = subagents.records(room_name)
    await subagents.release_ended(room_name)
    return [_read(e) for e in found]


@router.post("", response_model=SubagentRead, status_code=201, responses=refusals(404, 422))
async def start_subagent(room_name: str, payload: SubagentCreate, request: Request) -> SubagentRead:
    """Start a subagent of ``parent``'s: a member with its own handle,
    ``<parent>:<name>``, which its parent's token may act as."""
    _require_room(room_name)
    parent = actor.bind_delegated_actor(request, room_name, payload.parent, field="parent")
    if not parent:
        raise HTTPException(status_code=422, detail="Say whose subagent it is: `parent`.")
    try:
        return _read(subagents.start(room_name, parent, payload.name))
    except subagents.SubagentError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


@router.delete("/{handle}", response_model=SubagentRead, responses=refusals(403, 404))
async def end_subagent(room_name: str, handle: str, request: Request) -> SubagentRead:
    """End a subagent: it leaves the members, any row it claimed goes back to
    the board, and its messages stay its own."""
    _require_room(room_name)
    found = subagents.record(room_name, handle)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No subagent {handle} in {room_name}.")
    actor.authorize_handle(request, room_name, found["parent"], field="parent")
    ended = subagents.end(room_name, handle)
    assert ended is not None
    await subagents.release_ended(room_name)
    return _read(ended)
