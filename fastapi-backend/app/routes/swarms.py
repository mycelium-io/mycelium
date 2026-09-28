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
from app.routes.runners import existing_runner_of, runner_manifest
from app.schemas import MessageCreate, MessageType
from app.services import actor, runners, swarm, tasks, worker_engine, workspace
from app.services.agent_registry import write_agent_manifest
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
    runner: str | None = Field(
        None,
        description=(
            "Run the members on this runner's machine, in a herdr workspace, instead of as "
            "workers on the hub. The runner posts the kickoff once they are up"
        ),
    )
    framework: str | None = Field(
        None, description="With runner: the agent CLI each member runs (default: the first found)"
    )
    cwd: str | None = Field(None, description="With runner: the folder the members start in")
    worktree: bool = Field(False, description="With runner: a git worktree per member")


class SwarmRead(BaseModel):
    """Where the swarm is running: its room, its task, and the task's thread."""

    room: str
    key: str
    episode: str
    members: list[str]
    job: str | None = Field(None, description="With a runner: the job starting the members")


async def _start_on_runner(
    room_name: str, payload: SwarmCreate, task: str, team: list[str], me: str, request: Request
) -> SwarmRead:
    """A swarm whose members are agents on someone's machine, started by its runner.

    The hub does what it owns (the conductor, the members' manifests, the
    task) and queues one job; the runner opens the herdr workspace, briefs
    each member, and posts the kickoff when they are listening, which is the
    order ``mycelium swarm`` keeps from a terminal.
    """
    runner = runners.registry.get(payload.runner or "")
    if runner is None:
        raise HTTPException(status_code=404, detail="Runner not found")
    if payload.repo:
        raise HTTPException(
            status_code=422,
            detail="A repository is cloned by the hub for its own workers. Agents on a "
            "machine work in a folder there; pick the folder instead.",
        )
    framework = payload.framework or next(
        (f.id for f in runner.frameworks if f.installed and f.launchable), None
    )
    if framework is None:
        raise HTTPException(
            status_code=422, detail=f"{runner.label} has no agent CLI herdr can start."
        )
    try:
        runners.check_ready(runner)
        runners.check_framework(runner, framework)
        cwd = runners.check_cwd(runner, payload.cwd)
    except runners.RunnerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for handle in team:
        exists, started_by = existing_runner_of(room_name, handle)
        if exists and started_by != runner.id:
            raise HTTPException(
                status_code=409,
                detail=f"@{handle} is already a member of {room_name}, and not one "
                f"{runner.label} started.",
            )

    room_dir = get_room_dir(room_name)
    if read_memory_file(room_dir, f"agents/{swarm.CONDUCTOR}") is None:
        await create_engine(
            room_name,
            EngineCreate(handle=swarm.CONDUCTOR, kind="conductor", created_by=me),
            request,
        )
    for handle in team:
        await write_agent_manifest(
            room_name,
            handle,
            runner_manifest(
                framework=framework,
                runner=runner.id,
                cwd=cwd,
                description=f"swarm member ({framework}) on {runner.label}",
                owner=me if me != "web-ui" else runner.owner,
            ),
            created_by=me,
        )

    row = await tasks.create_task(room_name, task, created_by=me)
    episode = str(row.episode or "")
    job = runners.registry.enqueue(
        runner.id,
        "swarm",
        {
            "room": room_name,
            "key": row.key,
            "episode": episode,
            "task": task,
            "team": team,
            "framework": framework,
            "cwd": cwd,
            "worktree": payload.worktree,
            "kickoff": payload.kickoff,
        },
        created_by=me,
    )
    logger.info(
        "room %s: swarm of %d on runner %s (%s) for %s",
        room_name,
        len(team),
        runner.id,
        framework,
        row.key,
    )
    return SwarmRead(room=room_name, key=row.key, episode=episode, members=team, job=job.id)


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
    if payload.runner:
        return await _start_on_runner(room_name, payload, task, team, me, request)
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
