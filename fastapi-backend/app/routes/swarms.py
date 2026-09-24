# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /swarms — put a team of workers on a task, in one call.

What ``mycelium swarm --server`` does from the CLI, as one write the app can
make: a room named after the task (created if it is not there), a conductor
and a worker per member registered in it, the task filed, and the kickoff
posted in the task's thread. The team takes it from there.

Each step goes through the route that owns it — rooms, engines, messages —
rather than around it, so a swarm started here provisions its channel, is
checked for who may post, and summons the conductor exactly as the same
writes made one at a time would.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.routes.engines import EngineCreate, create_engine
from app.routes.messages import send_message
from app.routes.rooms import create_room
from app.schemas import MessageCreate, MessageType, RoomCreate
from app.services import actor, swarm, tasks
from app.services.filesystem import get_room_dir, read_memory_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/swarms", tags=["swarms"])


class SwarmCreate(BaseModel):
    """What a team should work on, and how big the team is."""

    task: str = Field(..., min_length=1, max_length=500, description="What the team works on")
    size: int = Field(swarm.DEFAULT_SIZE, ge=2, le=swarm.MAX_SIZE, description="How many workers")
    room: str | None = Field(
        None, max_length=100, description="Room to run in (default: named after the task)"
    )
    created_by: str | None = Field(None, description="Who is starting it")


class SwarmRead(BaseModel):
    """Where the swarm is running: its room, its task, and the task's thread."""

    room: str
    key: str
    episode: str
    members: list[str]


@router.post("", response_model=SwarmRead, status_code=201)
async def start_swarm(payload: SwarmCreate, request: Request) -> SwarmRead:
    """Start a team of workers on a task and return where to watch it."""
    task = payload.task.strip()
    if not task:
        raise HTTPException(status_code=422, detail="A swarm needs a task")
    room = (payload.room or "").strip() or swarm.room_slug(task)
    me = actor.bind_optional_actor(request, payload.created_by, field="created_by") or "web-ui"
    team = swarm.team_handles(payload.size)

    await create_room(RoomCreate(name=room, is_public=True))
    room_dir = get_room_dir(room)
    for handle, kind in [(swarm.CONDUCTOR, "conductor"), *((h, "worker") for h in team)]:
        # A room reused for a second swarm keeps the members it has.
        if read_memory_file(room_dir, f"agents/{handle}") is None:
            await create_engine(
                room, EngineCreate(handle=handle, kind=kind, created_by=me), request
            )

    row = await tasks.create_task(room, task, created_by=me)
    episode = str(row.episode or "")
    await send_message(
        room,
        MessageCreate(
            sender_handle=me,
            message_type=MessageType.BROADCAST,
            content=swarm.kickoff_text(team, task),
            episode=episode,
        ),
        request,
    )
    logger.info("room %s: swarm of %d started on %s by %s", room, len(team), row.key, me)
    return SwarmRead(room=room, key=row.key, episode=episode, members=team)
