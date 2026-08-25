# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Tasks API — putting a task on the board, thread and all.

POST /rooms/{room}/tasks  — create a task

Board-first creation is the half of the task model no other route can do. A
``memory set`` under ``work/`` writes a row, but the binding that makes the row a
*thread* is store-owned (:data:`~app.services.filesystem.SYSTEM_META`) and has no
wire form on the memory routes on purpose — otherwise anything over HTTP could
point a row at a conversation it was never part of. So minting is a capability of
this route rather than a field a caller supplies, and
:func:`~app.services.tasks.create_task` is the one place it happens.

A sibling router rather than a suffix on ``/memory`` for the same reason
``fields`` and ``leases`` are: that router ends in a ``{key:path}`` catch-all.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.schemas import MemoryRead
from app.services import actor, tasks
from app.services.filesystem import get_room_dir, read_memory_file, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/tasks", tags=["tasks"])

#: The frontmatter relation a child task points at its parent with. A typed
#: ontology edge (``app.services.links.RELATION_KEYS``), so decomposing a task
#: builds the same graph every other memory relation does rather than a
#: parent pointer only the board knows how to read.
PARENT_RELATION = "part-of"


class TaskCreate(BaseModel):
    title: str = Field(..., description="What the task is — the row's title")
    handle: str = Field(..., description="Who is creating it — recorded as the row's author")
    key: str | None = Field(
        None, description="Memory key to write (default: work/<slug of the title>)"
    )
    assignee: str | None = Field(
        None,
        description=(
            "Who the task is meant for. Not custody: holding it is a lease, which "
            "only its holder can take (POST /leases/claim)."
        ),
    )
    parent: str | None = Field(
        None,
        description=(
            "Memory key of the task this one decomposes — recorded as a "
            f"``{PARENT_RELATION}`` relation on the child."
        ),
    )


@router.post("", response_model=MemoryRead, status_code=201)
async def create_task(room_name: str, body: TaskCreate, request: Request) -> MemoryRead:
    """Create a task with its thread already minted."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")

    meta: dict[str, object] = {}
    if body.assignee:
        meta[tasks.ASSIGNEE_FIELD] = body.assignee.lstrip("@")
    if body.parent:
        # Refused rather than written: a relation naming a row the room does not
        # have is a dangling edge in the link index, and a decomposition that
        # silently loses its parent reads as a top-level task forever after.
        if read_memory_file(get_room_dir(room_name), body.parent) is None:
            raise HTTPException(
                status_code=404,
                detail=f"No task {body.parent!r} in room {room_name!r} to parent to",
            )
        meta[PARENT_RELATION] = body.parent

    return await tasks.create_task(
        room_name, body.title, created_by=handle, key=body.key, meta=meta
    )
