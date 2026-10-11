# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An ``@!handle`` mention: stop an agent mid-turn so it reads a message now.

A plain mention waits: the agent's wake is held until its turn ends, so a
correction ("stop, you're in the wrong checkout") lands after the work it
corrects. An interrupting mention asks the agent's machine to stop the turn
with its CLI's own key, keeping the session, and the wake the mention queued
is then delivered as soon as the agent is idle, worded so the agent acts on it
and carries on rather than taking the interrupt as "the person stopped me".

Three properties keep it safe.

**Only someone with the right to.** A person in the room may interrupt any
agent. An agent may interrupt another only when it is that agent's owner or in
its ``allow_from``, the same delegation every act-as check uses. Anything else
is an ordinary mention.

**Only a working agent.** An idle one is woken as for ``@handle`` and is sent
no key, since on an idle session the key could clear what a person was typing
into it. The hub checks herdr's status, and the runner checks again before it
presses anything.

**Only through the machine's runner.** The hub never reaches into a machine:
it queues an ``interrupt`` job for the connected runner whose machine runs the
agent, and that runner sends the key. An agent no runner reports gets the
mention without the interrupt.
"""

from __future__ import annotations

import logging

from app.services import principals
from app.services.agent_registry import norm_handle
from app.services.runners import RunnerError, registry

logger = logging.getLogger(__name__)

#: herdr states in which an agent is mid-turn, and so worth interrupting.
WORKING = frozenset({"working"})


def refusal(room: str, target: str, by: str | None) -> str | None:
    """Why ``by`` may not interrupt ``target`` in ``room``, or ``None`` if it may."""
    actor = norm_handle(by or "") or ""
    if not actor:
        return "nobody named sent it"
    if principals.classify_sender(room, actor) not in {"agent", "engine"}:
        return None
    if principals.delegates_to(room, target, actor):
        return None
    return (
        f"@{actor} is an agent, and @{target} doesn't name it as owner or in allow_from. "
        "A person may interrupt any agent; an agent only one it owns or leads."
    )


def runner_for(room: str, handle: str) -> tuple[str, str | None] | None:
    """``(runner id, pane)`` of the connected runner whose machine runs ``handle``."""
    for runner in registry.all():
        if not runner.connected:
            continue
        for agent in runner.agents:
            if (
                agent.room == room
                and agent.handle == handle
                and agent.status not in {"stopped", "failed"}
            ):
                return runner.id, agent.pane
        if runner.machine is None:
            continue
        for workspace in runner.machine.workspaces:
            for seen in workspace.agents:
                if seen.room == room and seen.handle == handle and seen.state != "gone":
                    return runner.id, seen.pane
    return None


def request(room: str, handle: str, by: str | None, status: str | None) -> bool:
    """Ask ``handle``'s machine to stop its turn, when ``by`` may and it is working.

    ``status`` is herdr's state for it as the hub last heard. ``True`` when an
    ``interrupt`` job was queued, so the wake can say it interrupted.
    """
    if status not in WORKING:
        return False
    if why := refusal(room, handle, by):
        logger.info("@!%s in %s from %s is a plain mention: %s", handle, room, by, why)
        return False
    found = runner_for(room, handle)
    if found is None:
        logger.info("@!%s in %s: no connected runner runs it", handle, room)
        return False
    runner_id, pane = found
    spec: dict[str, str] = {"room": room, "handle": handle}
    if pane:
        spec["pane"] = pane
    try:
        registry.enqueue(runner_id, "interrupt", spec, created_by=norm_handle(by or "") or by)
    except RunnerError:
        logger.warning("@!%s in %s: runner %s went away", handle, room, runner_id)
        return False
    return True
