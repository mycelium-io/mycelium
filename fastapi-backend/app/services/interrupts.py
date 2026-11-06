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

**Anyone named.** Any member of the room, a person, an agent or an engine, may
interrupt any agent, by the same rule as every other ask (``asks.py``), so an
agent can stop a teammate that is about to do something wrong. A message with
no sender named interrupts nobody.

**Only a working agent.** An idle one is woken as for ``@handle`` and is sent
no key, since on an idle session the key could clear what a person was typing
into it. The hub checks herdr's status, and the runner checks again before it
presses anything.

**Only through the machine's runner.** The hub never reaches into a machine:
it queues an ``interrupt`` job for the connected runner whose machine runs the
agent, and that runner sends the key. An agent no runner reports gets the
mention without the interrupt.

**A sent mention can become one, once.** A plain ``@handle`` to a working
agent reaches it when its turn ends. Its sender may turn that mention into an
interrupt after sending (:func:`upgrade`): only the sender, only for a member
the message mentioned, only while that member's wake for it is still held,
once per member per message, with no undo. The message's text never changes;
the interrupt is kept beside it (``log/interrupted.jsonl``), which is how the
app marks the message.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.services.agent_registry import norm_handle
from app.services.filesystem import room_exists, room_path, same_room
from app.services.runners import RunnerError, registry

logger = logging.getLogger(__name__)

#: Where a room keeps the interrupts made with messages already sent.
INTERRUPTED_FILE = "log/interrupted.jsonl"

#: One upgrade at a time per room, so "once per member per message" holds.
_upgrading: dict[str, asyncio.Lock] = {}


class Refused(Exception):
    """An interrupt the hub won't make, with the status to answer with."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Interrupted:
    """Who a message's sender interrupted with it, and when."""

    message: str
    by: str
    handle: str
    at: str

    def wire(self) -> dict[str, str]:
        return {"by": self.by, "handle": self.handle, "at": self.at}


def interrupted(room: str) -> dict[str, list[Interrupted]]:
    """Every interrupt made with a sent message in ``room``, by message id."""
    path = room_path(room) / INTERRUPTED_FILE
    found: dict[str, list[Interrupted]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            raw = json.loads(line)
            mark = Interrupted(
                str(raw["message"]), str(raw["by"]), str(raw["handle"]), str(raw["at"])
            )
        except (ValueError, KeyError, TypeError):
            continue
        found.setdefault(mark.message, []).append(mark)
    return found


def _keep(room: str, mark: Interrupted) -> None:
    # Into the room's own folder only while it has one: a room deleted
    # meanwhile isn't made again (a room is its folder).
    path = room_path(room) / INTERRUPTED_FILE
    if not room_exists(room):
        return
    path.parent.mkdir(exist_ok=True)
    line = {"message": mark.message, "by": mark.by, "handle": mark.handle, "at": mark.at}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def _find(room: str, ref: str) -> Any:
    """The transcript record ``ref`` names, or the start of one of its ids.

    A message has three: the history read's (what ``respond`` prints), the one
    it rode the channel under, and the one the send route returned to the
    client that posted it (what the app holds), so any of them finds it, as
    amend's lookup does.
    """
    from app.services import in_memory_store
    from app.services.persister import load_transcript, read_id

    ref = ref.strip().lower()
    if len(ref) < 4:
        raise Refused(422, "Name the message by its id (at least its first 4 characters).")
    posted = {
        m.message_id.lower()
        for m in in_memory_store.list_messages(room)
        if m.message_id and str(m.id).startswith(ref)
    }
    hits = [
        r
        for r in load_transcript(room)
        if str(read_id(r)).startswith(ref)
        or (r.message_id or "").lower().startswith(ref)
        or (r.message_id or "").lower() in posted
    ]
    if not hits:
        raise Refused(404, f"No message {ref} in {room}.")
    if len({str(read_id(r)) for r in hits}) > 1:
        raise Refused(422, f"{ref} names more than one message; give more of its id.")
    return hits[-1]


async def upgrade(room: str, ref: str, handle: str, by: str) -> Interrupted:
    """Turn ``by``'s plain ``@handle`` in the message ``ref`` into an interrupt.

    Stops ``handle``'s turn through its machine's runner, as an ``@!`` would,
    and raises the wake that message rang to an interrupt, so the agent reads
    it now and is told it was sent while it worked. Refused, saying why,
    unless ``by`` sent it, it mentions ``handle``, that wake is still held
    and ``handle`` is working, and nobody interrupted ``handle`` with it yet.
    """
    from app.services.asks import asked
    from app.services.persister import read_id, record_episode
    from app.services.room_channels import manager

    who = norm_handle(handle) or ""
    me = norm_handle(by) or ""
    async with _upgrading.setdefault(room, asyncio.Lock()):
        record = _find(room, ref)
        rid = str(read_id(record))
        short = rid[:8]
        sender = norm_handle(record.sender) or ""
        if me != sender:
            raise Refused(403, f"Only @{sender}, who sent {short}, can interrupt with it.")
        why = asked(record.content).get(who)
        if why is None:
            raise Refused(
                422,
                f"{short} doesn't mention @{who}. To ask it now, send a message with @!{who}.",
            )
        if any(m.handle == who for m in interrupted(room).get(rid, [])):
            raise Refused(
                409,
                f"@{who} was already interrupted with {short}. It's once per member per message.",
            )
        if why == "interrupt":
            raise Refused(409, f"{short} already interrupts @{who}: it says @!{who}.")
        status = manager.herdr_status(room, who)
        if status is None:
            raise Refused(
                409,
                f"@{who} isn't running anywhere Mycelium can stop it, so it reads {short} "
                "on its next await.",
            )
        if not manager.held_for(room, who, record.message_id):
            raise Refused(
                409, f"@{who} has {short} already, so there's nothing to interrupt it for."
            )
        if status not in WORKING:
            raise Refused(
                409,
                f"@{who} isn't working right now, so it reads {short} next without being stopped.",
            )
        if not request(room, who, me, status):
            raise Refused(
                409,
                f"@{who}'s machine can't be reached to stop it, so it reads {short} when its turn ends.",
            )
        manager.enqueue_herdr_wake(
            room,
            who,
            reason="interrupt",
            sender=me,
            episode=record_episode(record),
            message=record.message_id,
            interrupted=record.message_id,
        )
        mark = Interrupted(rid, me, who, datetime.now(UTC).isoformat())
        _keep(room, mark)
    _announce(room, mark)
    return mark


def _announce(room: str, mark: Interrupted) -> None:
    """Tell the room's open views, so the message's ⚡ shows without a reload.
    A frame for the app alone: the room's history gets no line for it."""
    from app.bus import bus, room_channel

    bus.publish(
        room_channel(room),
        {
            "type": "message_interrupted",
            "room_name": room,
            "message_id": mark.message,
            **mark.wire(),
        },
    )


#: herdr states in which an agent is mid-turn, and so worth interrupting.
WORKING = frozenset({"working"})


def refusal(room: str, target: str, by: str | None) -> str | None:
    """Why ``by`` may not interrupt ``target`` in ``room``, or ``None`` if it may."""
    actor = norm_handle(by or "") or ""
    if not actor:
        return "nobody named sent it"
    return None


def runner_for(room: str, handle: str) -> tuple[str, str | None] | None:
    """``(runner id, pane)`` of the connected runner whose machine runs ``handle``."""
    for runner in registry.all():
        if not runner.connected:
            continue
        for agent in runner.agents:
            if (
                same_room(agent.room, room)
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
