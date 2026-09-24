# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /rooms/{room}/swarms — put a team of workers on a task in a room, in one call.

A swarm is a task in a room people already work in, with a team on it, so it
is addressed under the room like a task is, and a room that is not there is
refused rather than made. What ``mycelium swarm --server`` and the app's Swarm
dialog do, as one write: a conductor and a worker per member registered in the
room (a member already there is kept), the task filed, and the kickoff posted
in the task's thread. The team takes it from there. Given a repository, the
hub clones it first, and each worker works in its own worktree of the clone.

Each step goes through the route that owns it — engines, messages — rather
than around it, so a swarm started here is checked for who may post and
summons the conductor exactly as the same writes made one at a time would.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.routes.engines import EngineCreate, create_engine
from app.routes.messages import send_message
from app.schemas import MessageCreate, MessageType
from app.services import actor, swarm, tasks, worker_engine, workspace
from app.services.filesystem import get_room_dir, read_memory_file, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/swarms", tags=["swarms"])


class SwarmCreate(BaseModel):
    """What a team should work on, and how big the team is."""

    task: str = Field(..., min_length=1, max_length=500, description="What the team works on")
    size: int = Field(swarm.DEFAULT_SIZE, ge=2, le=swarm.MAX_SIZE, description="How many workers")
    repo: str | None = Field(
        None,
        max_length=500,
        description=(
            "Repository the team works on, cloned on the hub: an https, ssh or git@ URL, "
            "or an absolute path on the hub (default: a new, empty one)"
        ),
    )
    created_by: str | None = Field(None, description="Who is starting it")
    kickoff: bool = Field(
        True,
        description=(
            "Post the kickoff now. A caller that wants to be listening first (the CLI's "
            "live view) sets this false and posts it itself"
        ),
    )


class SwarmRead(BaseModel):
    """Where the swarm is running: its room, its task, and the task's thread."""

    room: str
    key: str
    episode: str
    members: list[str]


@router.post("", response_model=SwarmRead, status_code=201)
async def start_swarm(room_name: str, payload: SwarmCreate, request: Request) -> SwarmRead:
    """Start a team of workers on a task in this room and return where to watch it."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    task = payload.task.strip()
    if not task:
        raise HTTPException(status_code=422, detail="A swarm needs a task")
    me = actor.bind_optional_actor(request, payload.created_by, field="created_by") or "web-ui"
    team = swarm.team_handles(payload.size)
    repo = (payload.repo or "").strip() or None

    # The clone comes first: a repository the hub cannot reach is said at once,
    # before there is a team in the room waiting on nothing.
    if repo is not None:
        if not worker_engine.tooled():
            raise HTTPException(
                status_code=422,
                detail="This hub's workers have no tools, so they cannot work on a repository",
            )
        try:
            await asyncio.to_thread(workspace.prepare, room_name, repo)
        except workspace.WorkspaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    room_dir = get_room_dir(room_name)
    for handle, kind in [(swarm.CONDUCTOR, "conductor"), *((h, "worker") for h in team)]:
        # A room that has swarmed before keeps the members it has.
        if read_memory_file(room_dir, f"agents/{handle}") is None:
            await create_engine(
                room_name, EngineCreate(handle=handle, kind=kind, created_by=me), request
            )

    row = await tasks.create_task(room_name, task, created_by=me)
    episode = str(row.episode or "")
    read = SwarmRead(room=room_name, key=row.key, episode=episode, members=team)
    if not payload.kickoff:
        logger.info("room %s: swarm of %d set up on %s by %s", room_name, len(team), row.key, me)
        return read
    await send_message(
        room_name,
        MessageCreate(
            sender_handle=me,
            message_type=MessageType.BROADCAST,
            content=swarm.kickoff_text(team, task),
            episode=episode,
        ),
        request,
    )
    logger.info("room %s: swarm of %d started on %s by %s", room_name, len(team), row.key, me)
    return read
