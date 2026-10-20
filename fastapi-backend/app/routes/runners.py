# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""/runners: the machines dialed in to this hub, and what the app asks of them.

A runner (``mycelium runner``) dials out: it says hello, heartbeats, and
long-polls ``jobs/next``. The app reads the runners and queues jobs: start an
agent, stop one, scan again. The hub never calls into a machine, so a laptop
behind NAT, or a hub on another continent, works the same as one on localhost.

Starting an agent is written here, not on the runner: the manifest and its
notes land in the room first, through the same upsert every writer uses, and
only then is the launch queued. A launch the runner then fails leaves an agent
defined in the room that can be started again, which is what the app shows.

The hub is not what keeps a machine safe. Anyone who can reach it can queue a
job, and nothing here can prove who asked, so the runner asks the person at
its machine before it starts anything (``mycelium/runner/approvals.py``). What
the hub does is keep machines to their owners when it can tell who is calling:
with a verified token, a caller sees and asks only runners it owns.
"""

from __future__ import annotations

import logging
import re

import yaml
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.schemas import (
    HANDLE_PATTERN,
    MachineRestart,
    MemoryBatchCreate,
    MemoryCreate,
    RunnerAgentAdopt,
    RunnerAgentLaunch,
    RunnerHello,
    RunnerJobRead,
    RunnerJobReport,
    RunnerPair,
    RunnerRead,
)
from app.services import actor
from app.services.agent_registry import norm_handle, write_agent_manifest
from app.services.filesystem import (
    canonical_room_name,
    get_room_dir,
    read_memory_file,
    room_exists,
    same_room,
)
from app.services.runners import (
    RunnerError,
    check_cwd,
    check_framework,
    check_ready,
    registry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runners", tags=["runners"])

_HANDLE_RE = re.compile(HANDLE_PATTERN)
#: The longest a runner's long-poll for its next job is held.
MAX_POLL_S = 30.0


def _yours(runner: RunnerRead, request: Request | None) -> bool:
    """Whether a verified caller owns ``runner``; any caller, when none is verified.

    Without a token the hub can't tell who is calling (the gate is off by
    default), so it shows every runner and the runner's own question is the
    only check. A runner that names no owner belongs to no one it could hide from.
    """
    principal = actor.current_principal(request)
    if principal is None or not runner.owner:
        return True
    return norm_handle(runner.owner) == norm_handle(principal.handle)


def _runner_or_404(runner_id: str, request: Request | None = None) -> RunnerRead:
    runner = registry.get(runner_id)
    if runner is None or not _yours(runner, request):
        raise HTTPException(status_code=404, detail="Runner not found")
    return runner


def adapter_for(framework: str) -> str:
    """The manifest adapter a framework's agents are recorded under.

    Every resident agent participates the same way (``await``/``respond``), so
    the adapter only matters where a family has install-time assets; the
    framework itself is recorded beside it. The CLI's
    ``integrations.agents.adapter_for`` answers the same from each CLI's kind.
    """
    return "cursor" if framework == "cursor" else "claude_code"


def notes_key(handle: str) -> str:
    return f"agents/{handle}/notes"


async def write_notes(room: str, handle: str, text: str, *, created_by: str) -> None:
    """Write an agent's notes, which it reads when it starts."""
    from app.routes.memory import upsert_memories  # lazy: routes import each other

    item = MemoryCreate(key=notes_key(handle), value=text, created_by=created_by, embed=False)
    await upsert_memories(room, MemoryBatchCreate(items=[item]))


def runner_manifest(
    *, framework: str, runner: str, cwd: str | None, description: str, owner: str | None
) -> dict:
    return {
        "adapter": adapter_for(framework),
        "framework": framework,
        "runner": runner,
        "cwd": cwd,
        "description": description,
        "allow_from": [],
        "owner": norm_handle(owner),
        "team": None,
    }


def existing_runner_of(room: str, handle: str) -> tuple[bool, str | None]:
    """Whether ``agents/<handle>`` exists in ``room``, and which runner started it."""
    found = read_memory_file(get_room_dir(room), f"agents/{handle}")
    if found is None:
        return False, None
    try:
        data = yaml.safe_load(found[1]) or {}
    except yaml.YAMLError:
        data = {}
    return True, (str(data["runner"]) if isinstance(data, dict) and data.get("runner") else None)


# ── the runner's side ────────────────────────────────────────────────────────


@router.post("", response_model=RunnerRead)
async def runner_hello(payload: RunnerHello) -> RunnerRead:
    """A runner dialing in, or its heartbeat: what it found on its machine, and what it runs."""
    return registry.hello(payload)


@router.delete("/{runner_id}", status_code=204)
async def runner_goodbye(runner_id: str) -> Response:
    """A runner going away; its agents stay defined in their rooms."""
    registry.remove(runner_id)
    return Response(status_code=204)


@router.get("/{runner_id}/jobs/next", response_model=RunnerJobRead | None)
async def next_job(
    runner_id: str, timeout: float = Query(25.0, ge=0.0, le=MAX_POLL_S)
) -> RunnerJobRead | Response:
    """The runner's long-poll: the next job to do, or 204 when none arrived in time."""
    try:
        job = await registry.next_job(runner_id, timeout)
    except RunnerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job is None:
        return Response(status_code=204)
    return job


@router.patch("/{runner_id}/jobs/{job_id}", response_model=RunnerJobRead)
async def report_job(runner_id: str, job_id: str, payload: RunnerJobReport) -> RunnerJobRead:
    """The runner saying how a job went.

    A ``rename`` reported running is the machine's yes: the hub renames the
    agent then, before the runner restarts it, so its first read under the new
    handle finds everything there. A rename the room no longer allows (the name
    was taken while it waited) answers ``failed``, and the runner restarts nothing.
    """
    queued = registry.job(runner_id, job_id)
    if (
        queued is not None
        and queued.kind == "rename"
        and payload.status == "running"
        and not queued.spec.get("applied")
    ):
        payload = await _apply_rename(queued, payload)
    try:
        job = registry.report(runner_id, job_id, payload)
    except RunnerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job.kind == "adopt" and job.status == "failed":
        await _forget_unadopted(runner_id, job.spec)
    return job


async def _apply_rename(job: RunnerJobRead, payload: RunnerJobReport) -> RunnerJobReport:
    """Rename the agent a ``rename`` job is for, now its machine said yes."""
    from app.services import agent_rename  # lazy: it reaches the room manager

    spec = job.spec
    try:
        await agent_rename.apply(
            str(spec.get("room")),
            str(spec.get("handle")),
            str(spec.get("to")),
            by=str(spec.get("by") or job.created_by or "unknown"),
        )
    except agent_rename.RenameError as exc:
        return RunnerJobReport(status="failed", error=f"Not renamed: {exc}")
    spec["applied"] = True
    return payload


async def _forget_unadopted(runner_id: str, spec: dict) -> None:
    """Take back the member an ``adopt`` wrote when the machine didn't map its pane.

    The member is written before the machine is asked, as a launch's is, but a
    declined launch can be started again and a declined adopt leaves a member
    with no pane. Every way an adopt fails is before the mapping, so the member
    goes, unless it has since become some other runner's.
    """
    from app.routes.memory import remove_memory  # lazy: routes import each other

    room, handle = str(spec.get("room") or ""), str(spec.get("handle") or "")
    if not room or not handle or not room_exists(room):
        return
    exists, owner = existing_runner_of(room, handle)
    if not exists or owner != runner_id:
        return
    try:
        await remove_memory(room, f"agents/{handle}")
    except HTTPException:
        logger.debug("adopt: @%s in %s was already gone", handle, room)


# ── the app's side ───────────────────────────────────────────────────────────


@router.get("", response_model=list[RunnerRead])
async def list_runners(request: Request) -> list[RunnerRead]:
    """Every machine heard from recently, connected ones first (a verified caller's own only)."""
    return [r for r in registry.all() if _yours(r, request)]


@router.post("/pair", response_model=RunnerJobRead, status_code=201)
async def pair_device(payload: RunnerPair, request: Request) -> RunnerJobRead:
    """Ask the machine that printed a pairing code to pair this device.

    The hub routes by the code's public part and carries the proof; only the
    machine can check it. Follow the returned job: ``done`` carries the
    pairing as the machine recorded it, ``failed`` says why not.
    """
    runner = registry.offering(payload.code_id)
    if runner is None or not _yours(runner, request):
        raise HTTPException(
            status_code=404,
            detail="No machine is waiting to pair with that code. Check it, or make a new one "
            "there with `mycelium runner pair`.",
        )
    me = actor.bind_optional_actor(request, None, field="created_by")
    spec = {
        "offer": payload.code_id.upper(),
        "name": payload.name,
        "key": payload.key.model_dump(),
        "proof": payload.proof,
    }
    logger.info("runner %s: pair '%s'", runner.id, payload.name)
    return registry.enqueue(runner.id, "pair", spec, created_by=me)


@router.get("/{runner_id}", response_model=RunnerRead)
async def get_runner(runner_id: str, request: Request) -> RunnerRead:
    return _runner_or_404(runner_id, request)


@router.get("/{runner_id}/jobs", response_model=list[RunnerJobRead])
async def list_jobs(runner_id: str, request: Request) -> list[RunnerJobRead]:
    """A runner's recent jobs, newest first."""
    _runner_or_404(runner_id, request)
    jobs = registry.jobs(runner_id)
    if jobs is None:
        raise HTTPException(status_code=404, detail="Runner not found")
    return jobs


@router.get("/{runner_id}/jobs/{job_id}", response_model=RunnerJobRead)
async def get_job(runner_id: str, job_id: str, request: Request) -> RunnerJobRead:
    _runner_or_404(runner_id, request)
    job = registry.job(runner_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{runner_id}/scan", response_model=RunnerJobRead, status_code=201)
async def rescan(runner_id: str, request: Request) -> RunnerJobRead:
    """Ask a runner to look for agent CLIs again; its next heartbeat carries what it found."""
    runner = _runner_or_404(runner_id, request)
    try:
        check_ready(runner)
    except RunnerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    me = actor.bind_optional_actor(request, None, field="created_by")
    return registry.enqueue(runner_id, "scan", {}, created_by=me)


@router.post("/{runner_id}/restart", response_model=RunnerJobRead, status_code=201)
async def restart_agents(
    runner_id: str, payload: MachineRestart, request: Request
) -> RunnerJobRead:
    """Start stopped agents on this machine again, as themselves.

    Any agent the machine reports, not only one this runner started. The
    runner asks the person at the machine first, as it does for a launch;
    ``mycelium machine restart`` does the same there.
    """
    runner = _runner_or_404(runner_id, request)
    if not payload.all and not payload.agents:
        raise HTTPException(status_code=422, detail="Say which agents to restart, or all.")
    try:
        check_ready(runner)
    except RunnerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    spec = {
        "all": payload.all,
        "agents": [{"handle": norm_handle(a.handle) or "", "room": a.room} for a in payload.agents],
    }
    me = actor.bind_optional_actor(request, None, field="created_by")
    logger.info("runner %s: restart %s", runner_id, spec)
    return registry.enqueue(runner_id, "restart", spec, created_by=me, signature=payload.signature)


@router.post("/{runner_id}/agents", response_model=RunnerJobRead, status_code=201)
async def launch_agent(
    runner_id: str, payload: RunnerAgentLaunch, request: Request
) -> RunnerJobRead:
    """Define an agent in a room and start it on this runner's machine.

    An agent this runner started before is started again (with new notes when
    instructions are given); a handle that names any other agent is refused.
    The runner asks the person at its machine before it starts it.
    """
    runner = _runner_or_404(runner_id, request)
    # The body names the room, so the request's path isn't where it's spelled.
    payload.room = canonical_room_name(payload.room)
    if not room_exists(payload.room):
        raise HTTPException(status_code=404, detail="Room not found")
    handle = norm_handle(payload.handle)
    if not handle or not _HANDLE_RE.match(handle):
        raise HTTPException(
            status_code=422,
            detail="Handle must be a lowercase slug (a-z, 0-9, '-', '_') starting alphanumeric.",
        )
    try:
        check_ready(runner)
        check_framework(runner, payload.framework)
        cwd = check_cwd(runner, payload.cwd)
    except RunnerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    exists, started_by = existing_runner_of(payload.room, handle)
    if exists and started_by != runner_id:
        raise HTTPException(
            status_code=409,
            detail=f"@{handle} is already a member of {payload.room}, and not one "
            f"{runner.label} started. Pick another handle.",
        )

    me = actor.bind_optional_actor(request, payload.created_by, field="created_by")
    owner = me or runner.owner
    await write_agent_manifest(
        payload.room,
        handle,
        runner_manifest(
            framework=payload.framework,
            runner=runner_id,
            cwd=cwd,
            description=payload.description,
            owner=owner,
        ),
        created_by=me or "web-ui",
        principal=actor.principal_handle(request),
    )
    instructions = (payload.instructions or "").strip()
    if instructions:
        await write_notes(payload.room, handle, instructions, created_by=me or "web-ui")

    spec = {
        "room": payload.room,
        "handle": handle,
        "framework": payload.framework,
        "cwd": cwd,
        "worktree": payload.worktree,
    }
    job = registry.enqueue(runner_id, "launch", spec, created_by=me, signature=payload.signature)
    logger.info(
        "runner %s: launch @%s (%s) in %s", runner_id, handle, payload.framework, payload.room
    )
    return job


@router.post("/{runner_id}/adopt", response_model=RunnerJobRead, status_code=201)
async def adopt_agent(runner_id: str, payload: RunnerAgentAdopt, request: Request) -> RunnerJobRead:
    """Bring an agent already running on this runner's machine into a room.

    The agent is one the machine reports as running in herdr and in no room
    (its report's ``unenrolled``). The member is written here first, owned by
    whoever asked, so it shows in the room at once; the runner then asks the
    person at the machine, maps the pane to the handle and introduces the
    agent once it's idle.
    """
    runner = _runner_or_404(runner_id, request)
    # The body names the room, so the request's path isn't where it's spelled.
    payload.room = canonical_room_name(payload.room)
    if not room_exists(payload.room):
        raise HTTPException(status_code=404, detail="Room not found")
    handle = norm_handle(payload.handle)
    if not handle or not _HANDLE_RE.match(handle):
        raise HTTPException(
            status_code=422,
            detail="Handle must be a lowercase slug (a-z, 0-9, '-', '_') starting alphanumeric.",
        )
    try:
        check_ready(runner)
    except RunnerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    unenrolled = runner.machine.unenrolled if runner.machine else []
    agent = next((a for a in unenrolled if a.pane == payload.pane), None)
    if agent is None:
        raise HTTPException(
            status_code=422,
            detail=f"{runner.label} doesn't report an agent in pane {payload.pane} that's "
            "outside every room. It may have joined one, or closed.",
        )
    exists, _ = existing_runner_of(payload.room, handle)
    if exists:
        raise HTTPException(
            status_code=409,
            detail=f"@{handle} is already a member of {payload.room}. Pick another handle.",
        )

    framework = agent.kind or "claude"
    me = actor.bind_optional_actor(request, payload.created_by, field="created_by")
    await write_agent_manifest(
        payload.room,
        handle,
        runner_manifest(
            framework=framework,
            runner=runner_id,
            cwd=agent.folder,
            description=f"Already running on {runner.label}, brought into the room",
            owner=me or runner.owner,
        ),
        created_by=me or "web-ui",
        principal=actor.principal_handle(request),
    )
    spec = {
        "room": payload.room,
        "handle": handle,
        "pane": payload.pane,
        "framework": framework,
        "cwd": agent.folder,
    }
    logger.info("runner %s: adopt %s as @%s in %s", runner_id, payload.pane, handle, payload.room)
    return registry.enqueue(runner_id, "adopt", spec, created_by=me)


@router.post(
    "/{runner_id}/agents/{room_name}/{handle}/stop", response_model=RunnerJobRead, status_code=201
)
async def stop_agent(
    runner_id: str, room_name: str, handle: str, request: Request
) -> RunnerJobRead:
    """Stop an agent this runner started. It stays defined in the room, to start again."""
    runner = _runner_or_404(runner_id, request)
    try:
        check_ready(runner)
    except RunnerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    h = norm_handle(handle) or ""
    found = next((a for a in runner.agents if same_room(a.room, room_name) and a.handle == h), None)
    if found is None:
        raise HTTPException(
            status_code=404, detail=f"{runner.label} isn't running @{h} in {room_name}"
        )
    me = actor.bind_optional_actor(request, None, field="created_by")
    # The room as the runner spelled it, which is what it looks its agents up by.
    return registry.enqueue(runner_id, "stop", {"room": found.room, "handle": h}, created_by=me)
