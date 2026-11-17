# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Pause, resume, stop, start and keep an agent, for its owner, and what it uses.

**Pause** keeps the agent's session. The hub records the pause (``pauses``),
which holds the agent's wakes from then on, and asks the machine running it
for a ``pause`` job: the runner stops a working agent's turn with its CLI's own
key and tells it this is a pause from Mycelium, not a correction, and to wait.
An agent no connected machine runs is still paused: nothing wakes it.

**Resume** ends the pause and queues a ``resumed`` wake, which outranks any
other and whose digest is everything that arrived while it was paused.

**Stop** frees the agent's memory: the machine interrupts it and ends its
process, keeping its pane and conversation. With ``close`` it closes the pane
too, which is the stop for good. Either ends any pause, since a stopped agent
has nothing to hold.

**Start** brings a stopped agent back: its machine restarts it in its pane,
in its own session when its CLI can resume one. Like any restart, the machine
asks the person there first.

**Keep** marks an agent to keep running: stopping agents in bulk (``mycelium
agent stop --idle``, the Agents pane's quick picks) leaves it out (``keeps``).

**Usage** is what each agent uses, from the machine reports runners send with
every heartbeat: its RAM, CPU, processes and how long it has been idle.

Only an agent's owner may do any of these. An agent with no owner on record
has nobody to protect it, so anyone may. "My agents" is every agent whose
manifest names the person as its owner.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from app.schemas import (
    AgentControlRead,
    AgentsUsageRead,
    AgentUsageRead,
    MachineUsageRead,
    PauseRead,
)
from app.services import interrupts, keeps, pauses
from app.services.agent_registry import norm_handle, room_agents
from app.services.filesystem import list_room_names, same_room
from app.services.runners import RunnerError, registry

logger = logging.getLogger(__name__)


class ControlError(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def _pause_read(room: str, handle: str, record: dict[str, str] | None) -> PauseRead | None:
    if record is None:
        return None
    return PauseRead(
        room=room, handle=handle, by=record["by"], at=datetime.fromisoformat(record["at"])
    )


#: What a manifest says when it knew no owner: the same as saying nothing.
NO_OWNER = frozenset({"unknown"})


def _owner(raw: str | None) -> str | None:
    owner = norm_handle(raw or "") or None
    return None if owner in NO_OWNER else owner


def owner_of(room: str, handle: str) -> tuple[bool, str | None]:
    """``(registered, owner)`` for ``handle`` in ``room``."""
    for agent in room_agents(room):
        if agent.handle == handle:
            return True, _owner(agent.owner)
    return False, None


def check(room: str, handle: str, by: str, verb: str = "pause") -> None:
    """Refuse anyone but the agent's owner, and an agent the room doesn't have.

    With no owner on record anyone may pause, resume or keep it, which only
    holds its wakes or marks it. Nobody may stop or start it from here: that
    ends or starts a process on someone's machine.
    """
    registered, owner = owner_of(room, handle)
    if not registered:
        raise ControlError(f"@{handle} isn't an agent in {room}.", 404)
    if owner and owner != by:
        raise ControlError(
            f"Only @{owner}, who owns @{handle}, can pause, resume, stop, start or keep it.", 403
        )
    if owner is None and verb in MACHINE_VERBS:
        raise ControlError(
            f"@{handle} has no owner on record, so it can't be {MACHINE_VERBS[verb]} from here. "
            "Do it on its machine, or set its owner first.",
            403,
        )


#: What reaches into someone's machine without asking there, so needs an owner.
MACHINE_VERBS = {"stop": "stopped", "start": "started"}


def _ask_runner(
    room: str,
    handle: str,
    kind: Literal["pause", "stop"],
    by: str,
    extra: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Queue ``kind`` for the connected runner running ``handle``: ``(runner, job)``."""
    found = interrupts.runner_for(room, handle)
    if found is None:
        return None, None
    runner_id, pane = found
    spec: dict[str, Any] = {"room": room, "handle": handle, "by": by, **(extra or {})}
    if pane:
        spec["pane"] = pane
    try:
        job = registry.enqueue(runner_id, kind, spec, created_by=by)
    except RunnerError:
        logger.warning("%s @%s in %s: runner %s went away", kind, handle, room, runner_id)
        return None, None
    return runner_id, job.id


def pause(room: str, handle: str, by: str) -> AgentControlRead:
    """Pause ``handle``; its machine, if one runs it, stops its turn and tells it."""
    already = pauses.is_paused(room, handle)
    record = pauses.pause(room, handle, by)
    runner, job = (None, None) if already else _ask_runner(room, handle, "pause", by)
    logger.info("room %s: @%s paused by @%s", room, handle, by)
    return AgentControlRead(
        room=room, handle=handle, paused=_pause_read(room, handle, record), runner=runner, job=job
    )


def resume(room: str, handle: str, by: str) -> AgentControlRead:
    """Resume ``handle``: its held wakes give way to one that says so."""
    from app.services.room_channels import manager

    if pauses.resume(room, handle) is not None:
        manager.enqueue_herdr_wake(room, handle, reason="resumed", sender=by)
        logger.info("room %s: @%s resumed by @%s", room, handle, by)
    return AgentControlRead(room=room, handle=handle)


def stop(room: str, handle: str, by: str, *, close: bool = False) -> AgentControlRead:
    """Ask the machine running ``handle`` to stop it: end its process and keep
    its pane, or with ``close``, close the pane too."""
    runner, job = _ask_runner(room, handle, "stop", by, {"close": close})
    if runner is None:
        raise ControlError(f"No connected machine is running @{handle} in {room}.", 409)
    pauses.resume(room, handle)
    logger.info(
        "room %s: @%s stopped by @%s%s", room, handle, by, " (pane closed)" if close else ""
    )
    return AgentControlRead(room=room, handle=handle, runner=runner, job=job)


def start(room: str, handle: str, by: str) -> AgentControlRead:
    """Ask the machine where ``handle`` was stopped to start it again, in its
    own session. The machine asks the person there first, as any restart does."""
    found = interrupts.runner_for(room, handle)
    if found is None:
        raise ControlError(f"No connected machine has @{handle} in {room} to start.", 409)
    runner_id = found[0]
    spec = {"all": False, "agents": [{"handle": handle, "room": room}]}
    try:
        job = registry.enqueue(runner_id, "restart", spec, created_by=by)
    except RunnerError as exc:
        raise ControlError(f"@{handle}'s machine went away: {exc}", 409) from exc
    logger.info("room %s: @%s started by @%s", room, handle, by)
    return AgentControlRead(room=room, handle=handle, runner=runner_id, job=job.id)


def keep(room: str, handle: str, by: str, *, on: bool = True) -> AgentControlRead:
    """Keep ``handle`` running when agents are stopped in bulk, or stop keeping it."""
    kept = keeps.keep(room, handle, by, on=on)
    logger.info("room %s: @%s %s by @%s", room, handle, "kept" if kept else "not kept", by)
    return AgentControlRead(room=room, handle=handle, keep=kept)


def usage(room: str | None = None, owner: str | None = None) -> AgentsUsageRead:
    """What each agent uses, from every connected runner's machine report: the
    agents in ``room``, or every agent ``owner`` owns, or both."""
    mine = set(owned_by(owner)) if owner else None
    machines: list[MachineUsageRead] = []
    rows: list[AgentUsageRead] = []
    owners: dict[tuple[str, str], str | None] = {}
    for runner in registry.all():
        if not runner.connected or runner.machine is None:
            continue
        report = runner.machine
        found = False
        for workspace in report.workspaces:
            for seen in workspace.agents:
                key = (seen.room, seen.handle)
                if seen.state == "gone" or (room is not None and not same_room(seen.room, room)):
                    continue
                if mine is not None and key not in mine:
                    continue
                if key not in owners:
                    owners[key] = owner_of(*key)[1]
                found = True
                state = seen.state
                if state in ("working", "idle", "blocked") and pauses.is_paused(*key):
                    state = "paused"
                rows.append(
                    AgentUsageRead(
                        room=seen.room,
                        handle=seen.handle,
                        owner=owners[key],
                        state=state,
                        kind=seen.kind,
                        runner=runner.id,
                        machine=report.machine,
                        pane=seen.pane,
                        keep=keeps.is_kept(*key),
                        ram_mb=seen.ram_mb,
                        cpu=seen.cpu,
                        up_s=seen.up_s,
                        idle_since=seen.idle_since,
                        processes=seen.processes,
                        subagents_open=seen.subagents_open,
                        restartable=seen.restartable,
                    )
                )
        if found:
            machines.append(
                MachineUsageRead(
                    runner=runner.id, machine=report.machine, ram_total_mb=report.ram_total_mb
                )
            )
    rows.sort(key=lambda r: (-(r.ram_mb or 0), r.handle))
    return AgentsUsageRead(machines=machines, agents=rows)


def owned_by(owner: str, room: str | None = None) -> list[tuple[str, str]]:
    """``(room, handle)`` of every agent ``owner`` owns, in ``room`` or every room."""
    rooms = [room] if room else list_room_names()
    found: list[tuple[str, str]] = []
    for name in rooms:
        found.extend(
            (name, a.handle)
            for a in room_agents(name)
            if _owner(a.owner) == owner and a.adapter != "engine"
        )
    return found


def paused_of(owner: str) -> list[PauseRead]:
    """Every pause on an agent ``owner`` owns, across rooms, for the status rail."""
    out: list[PauseRead] = []
    for room, handle in owned_by(owner):
        read = _pause_read(room, handle, pauses.get(room, handle))
        if read is not None:
            out.append(read)
    return out
