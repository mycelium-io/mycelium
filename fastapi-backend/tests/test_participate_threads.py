# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Participating in one thread rather than the whole room (#631).

``await --thread`` narrows the long-poll to a conversation scope and drains it off
a cursor of its own; ``respond --thread`` puts the reply back in that scope. Both
are additive — no ``thread`` is the room-level behaviour, unchanged.

Node-free: the SLIM channel is faked, and the transcript is seeded on disk (where
thread resolution reads it) as well as in the delivery log the poll drains.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from httpx import AsyncClient
from starlette.requests import Request

from app.routes import participate
from app.services import l9, persister
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content
from app.services.persister import DeliveryLog

ROOM = "thread-room"
_REQUEST = Request({"type": "http", "method": "GET", "path": "/await", "headers": []})


@pytest.fixture(autouse=True)
def _forget_last_tick():
    """The served-tick memo is process-global; keep one test's tick out of the next."""
    participate._last_tick.clear()
    yield
    participate._last_tick.clear()


def _record(
    message_id: str,
    *,
    to: str | None = None,
    sender: str = "avery",
    text: str = "",
    parents: list[str] | None = None,
    episode: str | None = None,
):
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode or l9.episode_urn(ROOM, "live"),
        sender=sender,
        sender_role="human",
        recipients=[to] if to else [],
        topic=l9.topic_urn(ROOM),
        message_id=message_id,
        parents=parents,
        payload_type="message",
    )
    body = text or (f"@{to} your turn" if to else "opening message")
    return persister.record_from(env, serialize_content(env, extra={"content": body}))


def _recipients_of(record) -> list[str]:
    actors = record.content["l9"]["header"]["participants"]["actors"]
    return [a["id"] for a in actors[1:]]


class _FakePersister:
    def __init__(self, log: DeliveryLog) -> None:
        self.log = log

    def advance_cursor(self, handle: str, pos: int) -> None:
        self.log.advance(handle, pos)


class _Managed:
    def __init__(self, log: DeliveryLog) -> None:
        self.persister = _FakePersister(log)


@pytest.fixture
def wired(monkeypatch):
    """Seed a room's transcript on disk and behind a faked await path."""

    def _wire(records: list) -> DeliveryLog:
        get_room_dir(ROOM)
        persister.write_transcript(ROOM, records)
        log = DeliveryLog()
        for record in records:
            # Recipients anchor an untracked handle's cursor at the message that
            # addresses it, exactly as a live broadcast would.
            log.record(record, delivered_to=set(), recipients=_recipients_of(record))
        managed = _Managed(log)

        async def _provision(_room):
            return managed

        monkeypatch.setattr(participate, "room_exists", lambda _r: True)
        monkeypatch.setattr(participate.actor, "authorize_handle", lambda *a, **k: None)
        monkeypatch.setattr(participate.room_channels.manager, "provision", _provision)
        monkeypatch.setattr(
            participate.room_channels.manager, "refresh_lease", lambda *a, **k: None
        )
        monkeypatch.setattr(participate, "_POLL_INTERVAL_S", 0.01)
        return log

    return _wire


@pytest.mark.asyncio
async def test_a_scoped_await_serves_only_its_thread(wired):
    """The tangle this is for: two conversations are live and @alice is addressed
    in both, but a scoped poll returns the one she asked for."""
    wired(
        [
            _record("m01", text="cache TTL?"),
            _record("m02", to="alice", parents=["m01"], text="@alice thoughts on the TTL?"),
            _record("m03", to="alice", text="@alice unrelated ping"),
        ]
    )
    turn = await participate.await_message(ROOM, _REQUEST, handle="alice", timeout=0, thread="m01")
    assert turn["message_id"] == "m02"
    assert turn["thread"] == "m01"


@pytest.mark.asyncio
async def test_draining_a_thread_leaves_the_room_backlog_alone(wired):
    """A thread has a cursor of its own, so working one conversation never eats
    the turns waiting in another."""
    wired(
        [
            _record("m01", text="cache TTL?"),
            _record("m02", to="alice", parents=["m01"], text="@alice thoughts on the TTL?"),
            _record("m03", to="alice", text="@alice unrelated ping"),
        ]
    )
    scoped = await participate.await_message(
        ROOM, _REQUEST, handle="alice", timeout=0, thread="m01"
    )
    assert scoped["message_id"] == "m02"

    room_level = await participate.await_message(ROOM, _REQUEST, handle="alice", timeout=0)
    assert room_level["message_id"] == "m02"  # still first in the room-level queue
    assert (await participate.await_message(ROOM, _REQUEST, handle="alice", timeout=0))[
        "message_id"
    ] == "m03"


@pytest.mark.asyncio
async def test_a_room_level_turn_names_its_thread(wired):
    """A resident watches the whole room and routes on the turn's ``thread``."""
    wired(
        [
            _record("m01", text="cache TTL?"),
            _record("m02", to="alice", parents=["m01"], text="@alice thoughts?"),
        ]
    )
    turn = await participate.await_message(ROOM, _REQUEST, handle="alice", timeout=0)
    assert turn["thread"] == "m01"


@pytest.mark.asyncio
async def test_an_unknown_thread_is_refused_rather_than_silently_awaited(wired):
    wired([_record("m01", to="alice")])
    with pytest.raises(participate.HTTPException) as exc:
        await participate.await_message(ROOM, _REQUEST, handle="alice", timeout=0, thread="zzz")
    assert exc.value.status_code == 404


# ── respond ──────────────────────────────────────────────────────────────────


@pytest.fixture
def reply_channel(monkeypatch):
    """A faked live channel that captures what ``/reply`` publishes."""
    from app.services import room_channels

    class _Persister:
        def __init__(self) -> None:
            self.log = DeliveryLog([])
            self.ingested: list[Any] = []

        def ingest_local(self, envelope: Any, content: dict, list_write: bool = False) -> None:
            self.ingested.append(envelope)

    class _Channel:
        async def send(self, envelope: Any, *, extra: dict | None = None) -> None:
            return None

    class _Managed:
        def __init__(self) -> None:
            self.channel = _Channel()
            self.persister = _Persister()

    managed = _Managed()

    class _Manager:
        async def provision(self, room: str, **_kw: Any) -> _Managed:
            return managed

        def refresh_lease(self, room: str, handle: str) -> None:
            return None

        async def send_as_custodian(self, room: str, handle: str, data: bytes) -> bool:
            return False

    monkeypatch.setattr(room_channels, "manager", _Manager())
    return managed


async def _room_with_agent(client: AsyncClient, records: list) -> None:
    """A room with @alice registered in it, plus a seeded transcript."""
    await client.post("/api/rooms", json={"name": ROOM})
    write_memory_file(
        get_room_dir(ROOM),
        "agents/alice",
        yaml.safe_dump({"adapter": "claude_code"}, sort_keys=False),
        created_by="tester",
    )
    persister.write_transcript(ROOM, records)


@pytest.mark.asyncio
async def test_a_reply_into_a_thread_hangs_off_its_root(client: AsyncClient, reply_channel):
    """Threading is the causal edge, so scoping a reply is naming what it follows."""
    await _room_with_agent(
        client, [_record("m01", text="cache TTL?"), _record("m02", parents=["m01"])]
    )
    resp = await client.post(
        f"/api/rooms/{ROOM}/reply", json={"handle": "alice", "text": "60s", "thread": "m01"}
    )
    assert resp.status_code == 200
    envelope = reply_channel.persister.ingested[0]
    assert envelope.header.message.parents == ["m01"]


@pytest.mark.asyncio
async def test_reply_to_threads_onto_the_named_message(client: AsyncClient, reply_channel):
    await _room_with_agent(client, [_record("m01", text="cache TTL?")])
    resp = await client.post(
        f"/api/rooms/{ROOM}/reply", json={"handle": "alice", "text": "60s", "reply_to": "m01"}
    )
    assert resp.status_code == 200
    assert reply_channel.persister.ingested[0].header.message.parents == ["m01"]


@pytest.mark.asyncio
async def test_a_chat_thread_is_not_pulled_back_into_a_negotiation(
    client: AsyncClient, reply_channel, monkeypatch
):
    """An episode outranks causality when assigning a thread, so a reply scoped to
    a chat thread has to leave the woken tick's episode behind — otherwise the
    named scope would be silently overridden."""
    await _room_with_agent(
        client, [_record("m01", text="cache TTL?"), _record("m02", parents=["m01"])]
    )
    episode = l9.episode_urn(ROOM, "ab12cd34")
    tick = _record("t1", to="alice", sender="aligner", episode=episode)
    monkeypatch.setitem(participate._last_tick, (ROOM, "alice"), tick.content)

    resp = await client.post(
        f"/api/rooms/{ROOM}/reply", json={"handle": "alice", "text": "60s", "thread": "m01"}
    )
    assert resp.status_code == 200
    envelope = reply_channel.persister.ingested[0]
    assert envelope.header.message.episode == l9.episode_urn(ROOM, "live")
    assert envelope.header.message.parents == ["m01", "t1"]


@pytest.mark.asyncio
async def test_an_unscoped_reply_still_answers_the_tick_that_woke_it(
    client: AsyncClient, reply_channel, monkeypatch
):
    """The default path is untouched: no thread, and the reply parents on its tick."""
    await _room_with_agent(client, [])
    episode = l9.episode_urn(ROOM, "ab12cd34")
    tick = _record("t1", to="alice", sender="aligner", episode=episode)
    monkeypatch.setitem(participate._last_tick, (ROOM, "alice"), tick.content)

    resp = await client.post(f"/api/rooms/{ROOM}/reply", json={"handle": "alice", "text": "60s"})
    assert resp.status_code == 200
    envelope = reply_channel.persister.ingested[0]
    assert envelope.header.message.episode == episode
    assert envelope.header.message.parents == ["t1"]
