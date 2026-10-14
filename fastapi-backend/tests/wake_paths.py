# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""One room, written to the way each sender writes, read by every wake path.

Three things decide whether a message asked an agent for something: the herdr
doorbell (a wake queued for it), ``await`` (the turn it hands over) and the
wake digest (the "asked for you" list the herdr-wakes route builds). When they
disagree an agent is woken with nothing to read, or reads a turn nobody rang
for. This module writes a message through the route or engine call that sends
it for real, and then asks each of the three what it decided, so a test can
hold them to one answer.

A room here is a real persister over a channel that sends nothing: no SLIM
node, but every write goes through the same ingest every message goes through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml
from httpx import AsyncClient
from starlette.requests import Request

from app.routes import participate
from app.services import message_format, room_channels, turns, wake_log
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.message_models import Kind
from app.services.persister import RoomPersister, envelope_sender

ROOM = "asks-room"
#: The agent a row asks about, unless it names another.
AGENT = "coder"
#: Another agent, the one that replies and is replied to.
PEER = "planner"
#: A person, posting from the app.
PERSON = "hay"
#: The engines, by handle, and the kind each is registered as.
ENGINES = {
    "aligner": "aligner",
    "conductor": "conductor",
    "sage": "persona",
    "builder": "worker",
}
#: An A2A agent, answering for a remote endpoint.
REMOTE = "remote"

_REQUEST = Request({"type": "http", "method": "GET", "path": "/await", "headers": []})


class _QuietChannel:
    """A channel that sends nothing: the transcript is all a row needs."""

    async def send(self, *_a: Any, **_k: Any) -> None:
        return None

    def note_delivered(self, _envelope: Any) -> None:
        return None


@dataclass
class Room:
    """The room a row is written into, and what its paths decided."""

    client: AsyncClient
    managed: room_channels.ManagedRoomChannel
    thread: str = ""
    sent: list[str] = field(default_factory=list)

    @property
    def log(self) -> Any:
        assert self.managed.persister is not None
        return self.managed.persister.log


def _manifest(handle: str, body: dict[str, Any]) -> None:
    write_memory_file(
        get_room_dir(ROOM), f"agents/{handle}", yaml.safe_dump(body), created_by=PERSON
    )


async def open_room(client: AsyncClient, monkeypatch: Any) -> Room:
    """A room with two herdr agents, a person, the engines and an A2A agent."""
    from app.config import settings
    from app.services import interrupts

    manager = room_channels.manager
    monkeypatch.setattr(settings, "SLIM_ENABLED", True)
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    monkeypatch.setattr(manager, "_herdr_wakes", {})
    monkeypatch.setattr(manager, "invite_in_background", lambda *_a, **_k: None)
    # ``await`` with no timeout waits its longest; here that is one poll, so a
    # message it doesn't hand over answers at once rather than after an hour.
    monkeypatch.setattr(participate, "_POLL_INTERVAL_S", 0.001)
    monkeypatch.setattr(participate, "_MAX_WAIT_S", 0.005)
    monkeypatch.setattr(participate.actor, "authorize_handle", lambda *_a, **_k: None)
    # Whether a sender may stop a working agent is the interrupt module's own
    # question; every sender may here, so a row reads what the paths do with one.
    monkeypatch.setattr(interrupts, "request", lambda *_a, **_k: True)

    assert (await client.post("/api/rooms", json={"name": ROOM})).status_code in (200, 201)
    for handle in (AGENT, PEER):
        _manifest(handle, {"adapter": "claude_code", "owner": PERSON})
    for handle, kind in ENGINES.items():
        _manifest(handle, {"adapter": "engine", "kind": kind})
    _manifest(REMOTE, {"adapter": "a2a", "url": "https://remote.example/a2a"})

    _ring_turns(manager, monkeypatch)
    managed = room_channels.ManagedRoomChannel(
        room=ROOM,
        workspace="asks",
        client=None,  # ty: ignore[invalid-argument-type]  # nothing here dials SLIM
        channel=_QuietChannel(),  # ty: ignore[invalid-argument-type]
    )
    # Built as the manager builds a room's persister, minus the SLIM members.
    managed.persister = RoomPersister(
        ROOM,
        channel=managed.channel,
        members_provider=lambda: set(),
        on_summon=manager._summon_adapter(ROOM),
        on_addressed=manager._addressed_adapter(ROOM),
        feed_bus=False,
    )
    monkeypatch.setitem(manager._channels, ROOM, managed)
    manager.set_herdr_presence(ROOM, {AGENT: "idle", PEER: "idle"})
    room = Room(client=client, managed=managed)
    task = await client.post(
        f"/api/rooms/{ROOM}/tasks", json={"title": "Parser work", "handle": PERSON}
    )
    assert task.status_code == 201, task.text
    room.thread = task.json()["episode"]
    return room


def _ring_turns(manager: Any, monkeypatch: Any) -> None:
    """The doorbell half of ``main.py``'s addressed dispatch, which the app's
    startup wires and a test client never runs."""

    def ring(room: str, handle: str, envelope: Any, _text: str) -> None:
        manager.herdr_wake_addressed(
            room,
            handle,
            sender=envelope_sender(envelope),
            episode=envelope.header.message.episode if envelope.header.message else None,
        )

    monkeypatch.setattr(manager, "on_addressed", ring)


# ── Writing ──────────────────────────────────────────────────────────────────


def episode_of(room: Room, where: str) -> str:
    return room.thread if where == "thread" else message_format.live_episode_urn(ROOM)


async def _person(room: Room, text: str, episode: str) -> None:
    body: dict[str, Any] = {"sender_handle": PERSON, "message_type": "broadcast", "content": text}
    if episode != message_format.live_episode_urn(ROOM):
        body["episode"] = episode
    response = await room.client.post(f"/api/rooms/{ROOM}/messages", json=body)
    assert response.status_code in (200, 201), response.text


def _turn_from(sender: str, episode: str) -> dict[str, Any]:
    """The content of a turn ``sender`` put, as ``await`` last handed it."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        topic=message_format.topic_urn(ROOM),
        payload_type="message",
    )
    return {"l9": message_format.envelope_to_dict(env), "content": "earlier turn"}


async def _respond(room: Room, sender: str, text: str, episode: str, heard_from: str | None):
    """``mycelium respond``: the real route, after a turn from ``heard_from``."""
    key = (ROOM, sender)
    if heard_from:
        participate._last_tick[key] = _turn_from(heard_from, episode)
    else:
        participate._last_tick.pop(key, None)
    body: dict[str, Any] = {"handle": sender, "text": text}
    if episode != message_format.live_episode_urn(ROOM):
        body["episode"] = episode
    response = await room.client.post(f"/api/rooms/{ROOM}/reply", json=body)
    participate._last_tick.pop(key, None)
    assert response.status_code == 200, response.text


async def _post(
    room: Room,
    sender: str,
    text: str,
    episode: str,
    *,
    payload: str = "message",
    to: tuple[str, ...] = (),
    kind: Kind = Kind.exchange,
) -> None:
    """An engine's post: the envelope it builds, through ``ManagedRoomChannel.post``."""
    env = message_format.build_envelope(
        kind=kind,
        subkind="converged" if kind == Kind.commit else None,
        episode=episode,
        sender=sender,
        sender_role="agent",
        recipients=list(to),
        topic=message_format.topic_urn(ROOM),
        payload_type=payload,
    )
    await room.managed.post(env, text, list_write=True)


async def say(
    room: Room,
    sender: str,
    text: str = "",
    *,
    where: str = "room",
    to: tuple[str, ...] = (),
    shape: str | None = None,
) -> None:
    """Write one message as ``sender`` would send it.

    ``shape`` picks the sender's path when its handle alone doesn't: ``turn``
    (the aligner or the conductor putting a step to ``to``), ``ping``,
    ``notice``, ``presence`` or ``commit``. An agent replies through
    ``respond`` after a turn from ``to[0]``, if any.
    """
    episode = episode_of(room, where)
    manager = room_channels.manager
    if shape == "ping":
        await manager.raise_ping(ROOM, episode=room.thread, sender=sender, message_id="m-ping")
    elif shape == "notice":
        await manager.raise_notice(
            ROOM, subkind="claimed", key="work/parser-work", title="Parser work", by=sender
        )
    elif shape == "presence":
        await _post(room, sender, "", episode, payload="presence", to=to)
    elif shape == "commit":
        await _post(room, sender, text, episode, payload="outcome", to=to, kind=Kind.commit)
    elif shape == "turn":
        await _post(room, sender, text, episode, payload="message", to=to)
    elif sender == PERSON:
        await _person(room, text, episode)
    elif sender in (AGENT, PEER):
        await _respond(room, sender, text, episode, to[0] if to else None)
    elif ENGINES.get(sender) == "persona":
        await _post(room, sender, turns.neutralize_mentions(text), episode, payload="reply")
    elif ENGINES.get(sender) == "worker":
        await _post(room, sender, text, episode, payload="reply")
        # The worker rings the teammates it named itself (``worker_engine``).
        manager.enqueue_herdr_wakes_for_mentions(ROOM, text, exclude=sender, episode=episode)
    elif sender == REMOTE:
        # The A2A bridge answers whoever summoned it (``a2a_bridge``).
        await _post(room, sender, text, episode, payload="reply", to=to)
    else:
        await _post(room, sender, text, episode, to=to)


# ── Reading ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Decided:
    """What each path decided about one message and one agent."""

    doorbell: str | None  # the reason a wake was queued with, or None
    awaited: bool  # whether ``await`` handed the message over as a turn
    digest: bool  # whether the digest listed it as asking for the agent

    @property
    def asked(self) -> set[bool]:
        """Each path's yes or no; one value when they agree."""
        return {self.doorbell is not None, self.awaited, self.digest}


def mark_read(room: Room, agent: str) -> None:
    """``agent`` has read everything so far, so a row reads only its message."""
    room.log.advance(agent, len(room.log.records))
    participate._last_tick.pop((ROOM, agent), None)


async def decided(room: Room, agent: str) -> Decided:
    """Ask the doorbell, then the digest, then ``await`` about what was written
    since :func:`mark_read`. The order matters: ``await`` moves the read cursor
    the digest counts from, and the digest's route drains the doorbell's queue."""
    manager = room_channels.manager
    queued = [w for w in manager._herdr_wakes.get(ROOM, []) if w["handle"] == agent]
    doorbell = queued[0]["reason"] if queued else None
    manager._herdr_wakes[ROOM] = []

    # A wake that needs no message, so the route hands it whatever it covers.
    manager.set_herdr_presence(ROOM, {AGENT: "idle", PEER: "idle", agent: "idle"})
    manager.enqueue_herdr_wake(ROOM, agent, reason="assigned", key="work/parser-work")
    response = await room.client.get(f"/api/rooms/{ROOM}/sessions/herdr-wakes")
    assert response.status_code == 200, response.text
    (entry,) = wake_log.read(ROOM, agent=agent, limit=1)
    digest = bool(entry.get("messages"))
    manager.set_herdr_presence(ROOM, {AGENT: "idle", PEER: "idle"})

    result = await participate.await_message(ROOM, _REQUEST, handle=agent, timeout=0)
    return Decided(doorbell=doorbell, awaited=bool(result.get("message_id")), digest=digest)
