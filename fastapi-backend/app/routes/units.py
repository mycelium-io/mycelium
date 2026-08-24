# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Units API — putting a unit of work on the board, thread and all.

POST /rooms/{room}/units  — create a unit of work

Board-first creation is the half of the unit model no other route can do. A
``memory set`` under ``work/`` writes a row, but the binding that makes the row a
*thread* is store-owned (:data:`~app.services.filesystem.SYSTEM_META`) and has no
wire form on the memory routes on purpose — otherwise anything over HTTP could
point a row at a conversation it was never part of. So minting is a capability of
this route rather than a field a caller supplies, and
:func:`~app.services.units.create_unit` is the one place it happens.

A sibling router rather than a suffix on ``/memory`` for the same reason
``fields`` and ``leases`` are: that router ends in a ``{key:path}`` catch-all.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.schemas import MemoryRead
from app.services import actor, units
from app.services.filesystem import get_room_dir, read_memory_file, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/units", tags=["units"])

#: The frontmatter relation a child unit points at its parent with. A typed
#: ontology edge (``app.services.links.RELATION_KEYS``), so decomposing a unit
#: builds the same graph every other memory relation does rather than a
#: parent pointer only the board knows how to read.
PARENT_RELATION = "part-of"


class UnitCreate(BaseModel):
    title: str = Field(..., description="What the unit of work is — the row's title")
    handle: str = Field(..., description="Who is creating it — recorded as the row's author")
    key: str | None = Field(
        None, description="Memory key to write (default: work/<slug of the title>)"
    )
    assignee: str | None = Field(
        None,
        description=(
            "Who the unit is meant for. Not custody: holding it is a lease, which "
            "only its holder can take (POST /leases/claim)."
        ),
    )
    parent: str | None = Field(
        None,
        description=(
            "Memory key of the unit this one decomposes — recorded as a "
            f"``{PARENT_RELATION}`` relation on the child."
        ),
    )


@router.post("", response_model=MemoryRead, status_code=201)
async def create_unit(room_name: str, body: UnitCreate, request: Request) -> MemoryRead:
    """Create a unit of work with its thread already minted."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")

    meta: dict[str, object] = {}
    if body.assignee:
        meta[units.ASSIGNEE_FIELD] = body.assignee.lstrip("@")
    if body.parent:
        # Refused rather than written: a relation naming a row the room does not
        # have is a dangling edge in the link index, and a decomposition that
        # silently loses its parent reads as a top-level unit forever after.
        if read_memory_file(get_room_dir(room_name), body.parent) is None:
            raise HTTPException(
                status_code=404,
                detail=f"No unit {body.parent!r} in room {room_name!r} to parent to",
            )
        meta[PARENT_RELATION] = body.parent

    return await units.create_unit(
        room_name, body.title, created_by=handle, key=body.key, meta=meta
    )
