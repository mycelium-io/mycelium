# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Pause, resume and stop an agent, for its owner.

**Pause** keeps the agent's session. The hub records the pause (``pauses``),
which holds the agent's wakes from then on, and asks the machine running it
for a ``pause`` job: the runner stops a working agent's turn with its CLI's own
key and tells it this is a pause from Mycelium, not a correction, and to wait.
An agent no connected machine runs is still paused: nothing wakes it.

**Resume** ends the pause and queues a ``resumed`` wake, which outranks any
other and whose digest is everything that arrived while it was paused.

**Stop** is the hard stop: the machine interrupts the agent and closes its
pane. It ends any pause too, since a stopped agent has nothing to hold.

Only an agent's owner may do any of these. An agent with no owner on record
has nobody to protect it, so anyone may. "My agents" is every agent whose
manifest names the person as its owner.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from app.schemas import AgentControlRead, PauseRead
from app.services import interrupts, pauses
from app.services.agent_registry import norm_handle, room_agents
from app.services.filesystem import list_room_names
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


def owner_of(room: str, handle: str) -> tuple[bool, str | None]:
    """``(registered, owner)`` for ``handle`` in ``room``."""
    for agent in room_agents(room):
        if agent.handle == handle:
            return True, norm_handle(agent.owner or "") or None
    return False, None


def check(room: str, handle: str, by: str) -> None:
    """Refuse anyone but the agent's owner, and an agent the room doesn't have."""
    registered, owner = owner_of(room, handle)
    if not registered:
        raise ControlError(f"@{handle} isn't an agent in {room}.", 404)
    if owner and owner != by:
        raise ControlError(f"Only @{owner}, who owns @{handle}, can pause, resume or stop it.", 403)


def _ask_runner(
    room: str, handle: str, kind: Literal["pause", "stop"], by: str
) -> tuple[str | None, str | None]:
    """Queue ``kind`` for the connected runner running ``handle``: ``(runner, job)``."""
    found = interrupts.runner_for(room, handle)
    if found is None:
        return None, None
    runner_id, pane = found
    spec: dict[str, str] = {"room": room, "handle": handle, "by": by}
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


def stop(room: str, handle: str, by: str) -> AgentControlRead:
    """Ask the machine running ``handle`` to stop it and close its pane."""
    runner, job = _ask_runner(room, handle, "stop", by)
    if runner is None:
        raise ControlError(f"No connected machine is running @{handle} in {room}.", 409)
    pauses.resume(room, handle)
    logger.info("room %s: @%s stopped by @%s", room, handle, by)
    return AgentControlRead(room=room, handle=handle, runner=runner, job=job)


def owned_by(owner: str, room: str | None = None) -> list[tuple[str, str]]:
    """``(room, handle)`` of every agent ``owner`` owns, in ``room`` or every room."""
    rooms = [room] if room else list_room_names()
    found: list[tuple[str, str]] = []
    for name in rooms:
        found.extend(
            (name, a.handle)
            for a in room_agents(name)
            if norm_handle(a.owner or "") == owner and a.adapter != "engine"
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
