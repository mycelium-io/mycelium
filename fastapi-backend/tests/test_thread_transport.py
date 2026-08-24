# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Writing into a thread, waking on one, and the ping that surfaces it (#837).

A unit of work's thread is a tag over the room's own channel, so the transport
that reaches it is the room's transport with one field on it. These tests hold
the three things that field has to be worth: a write can be *targeted* at a
thread and is refused when it may not be, a wake can be *scoped* to one without
eating the room inbox behind it, and a thread write leaves the room itself
carrying a ping — a signal that a unit moved, never an echo of what was said.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from app.routes import participate
from app.services import l9, persister, units
from app.services.filesystem import get_room_dir
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content

ROOM = "threaded"
THREAD = l9.episode_urn(ROOM, "t3")
OTHER_THREAD = l9.episode_urn(ROOM, "t9")

_REQUEST = Request({"type": "http", "method": "GET", "path": "/await", "headers": []})


def _record(message_id: str, *, to: str, episode: str, sender: str = "avery"):
    """A human exchange @-addressed to ``to``, riding ``episode``."""
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        sender_role="human",
        recipients=[to],
        topic=l9.topic_urn(ROOM),
        message_id=message_id,
        payload_type="message",
    )
    return persister.record_from(env, serialize_content(env, extra={"content": f"@{to} hello"}))


class _FakePersister:
    """The delivery half of RoomPersister: a log, and both cursors over it."""

    def __init__(self, log: persister.DeliveryLog) -> None:
        self.log = log
        self.episode_cursors = persister.EpisodeCursors()

    def advance_cursor(self, handle: str, pos: int) -> None:
        self.log.advance(handle, pos)

    def episode_position(self, handle: str, episode: str) -> int:
        return self.episode_cursors.position(handle, episode, default=self.log.position(handle))

    def advance_episode_cursor(self, handle: str, episode: str, pos: int) -> None:
        self.episode_cursors.advance(handle, episode, pos, limit=len(self.log.records))


@pytest.fixture
def wired(monkeypatch):
    """Point the await route at a transcript the test controls."""

    def _wire(log: persister.DeliveryLog) -> _FakePersister:
        fake = _FakePersister(log)
        managed = type("_Managed", (), {"persister": fake})()

        async def _provision(_room):
            return managed

        monkeypatch.setattr(participate, "room_exists", lambda _r: True)
        monkeypatch.setattr(participate.actor, "authorize_handle", lambda *a, **k: None)
        monkeypatch.setattr(participate.room_channels.manager, "provision", _provision)
        monkeypatch.setattr(
            participate.room_channels.manager, "refresh_lease", lambda *a, **k: None
        )
        monkeypatch.setattr(participate, "_POLL_INTERVAL_S", 0.01)
        return fake

    return _wire


class TestScopedAwait:
    """``await --episode`` wakes on one thread, and only on that thread."""

    @pytest.mark.asyncio
    async def test_it_wakes_on_its_own_thread(self, wired):
        log = persister.DeliveryLog()
        log.record(_record("m1", to="api", episode=THREAD), delivered_to=set(), recipients=["api"])

        wired(log)
        result = await participate.await_message(
            ROOM, _REQUEST, handle="api", timeout=0, episode=THREAD
        )
        assert result["message_id"] == "m1"
        assert result["episode"] == THREAD

    @pytest.mark.asyncio
    async def test_a_turn_in_another_thread_is_not_its_turn(self, wired):
        """Scoping to a unit is the whole point: the room's noise stays out."""
        log = persister.DeliveryLog()
        log.record(
            _record("m1", to="api", episode=OTHER_THREAD), delivered_to=set(), recipients=["api"]
        )
        log.record(
            _record("m2", to="api", episode=l9.live_episode_urn(ROOM)),
            delivered_to=set(),
            recipients=["api"],
        )

        wired(log)
        result = await participate.await_message(
            ROOM, _REQUEST, handle="api", timeout=1, episode=THREAD
        )
        assert result["message"] is None

    @pytest.mark.asyncio
    async def test_watching_a_thread_leaves_the_room_inbox_alone(self, wired):
        """The two cursors are independent — draining one must not drain the other.

        An agent that spends a turn on a unit still has its room mentions waiting
        when it looks; the reverse of the bug a single shared cursor would cause.
        """
        log = persister.DeliveryLog()
        log.record(
            _record("room-1", to="api", episode=l9.live_episode_urn(ROOM)),
            delivered_to=set(),
            recipients=["api"],
        )
        log.record(_record("t-1", to="api", episode=THREAD), delivered_to=set(), recipients=["api"])

        wired(log)
        threaded = await participate.await_message(
            ROOM, _REQUEST, handle="api", timeout=0, episode=THREAD
        )
        assert threaded["message_id"] == "t-1"

        room_wide = await participate.await_message(ROOM, _REQUEST, handle="api", timeout=0)
        assert room_wide["message_id"] == "room-1"

    @pytest.mark.asyncio
    async def test_a_served_thread_turn_is_not_served_twice(self, wired):
        log = persister.DeliveryLog()
        log.record(_record("t-1", to="api", episode=THREAD), delivered_to=set(), recipients=["api"])

        wired(log)
        first = await participate.await_message(
            ROOM, _REQUEST, handle="api", timeout=0, episode=THREAD
        )
        assert first["message_id"] == "t-1"

        again = await participate.await_message(
            ROOM, _REQUEST, handle="api", timeout=1, episode=THREAD
        )
        assert again["message"] is None

    @pytest.mark.asyncio
    async def test_the_thread_position_survives_a_restart(self, wired, tmp_path, monkeypatch):
        """The cursor is persisted, so a restart resumes rather than re-serving."""
        monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
        persister.write_episode_cursors(ROOM, {THREAD: {"api": 1}})
        assert persister.load_episode_cursors(ROOM) == {THREAD: {"api": 1}}

        log = persister.DeliveryLog()
        log.record(_record("t-1", to="api", episode=THREAD), delivered_to=set(), recipients=["api"])
        fake = _FakePersister(log)
        fake.episode_cursors = persister.EpisodeCursors(persister.load_episode_cursors(ROOM))
        assert fake.episode_position("api", THREAD) == 1  # already served, before the restart


class TestThreadWriteAuthorization:
    """Naming a thread is not how one comes into being, and a frozen roster holds."""

    def test_the_room_itself_is_always_writable(self):
        assert units.episode_write_rejection(ROOM, "api", None) is None
        assert units.episode_write_rejection(ROOM, "api", l9.live_episode_urn(ROOM)) is None

    def test_an_invented_thread_is_refused(self):
        refusal = units.episode_write_rejection(ROOM, "api", THREAD)
        assert refusal is not None
        assert refusal.status == 404

    def test_a_thread_the_room_has_spoken_in_is_writable(self):
        assert units.episode_write_rejection(ROOM, "api", THREAD, transcript={THREAD}) is None

    def test_a_bound_row_makes_its_thread_writable(self, tmp_path, monkeypatch):
        """A unit's thread is writable from the moment the row carries it — before
        anything has been said in it, which is exactly when the first write lands."""
        monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
        get_room_dir(ROOM)
        monkeypatch.setattr(units, "bound_episodes", lambda _room: {THREAD})
        assert units.episode_write_rejection(ROOM, "api", THREAD) is None

    def test_an_outsider_cannot_drop_a_position_into_a_negotiation(self):
        """L9's stable-membership rule, enforced on the write side: a score across
        a frozen roster means nothing if anyone can post into it."""
        refusal = units.episode_write_rejection(
            ROOM,
            "mallory",
            THREAD,
            frozen_episode=THREAD,
            frozen_members={"api", "sec"},
            transcript={THREAD},
        )
        assert refusal is not None
        assert refusal.status == 403
        assert "mallory" in refusal.detail

    def test_a_member_of_the_negotiation_may_write(self):
        assert (
            units.episode_write_rejection(
                ROOM,
                "@API",
                THREAD,
                frozen_episode=THREAD,
                frozen_members={"api"},
                transcript={THREAD},
            )
            is None
        )

    def test_a_container_takes_a_newcomer(self):
        """A unit outlives what happens inside it, so an agent that claims the row
        after the thread opened can speak in it. The freeze is the negotiation's."""
        assert (
            units.episode_write_rejection(
                ROOM,
                "newcomer",
                THREAD,
                frozen_episode=OTHER_THREAD,
                frozen_members={"api"},
                transcript={THREAD, OTHER_THREAD},
            )
            is None
        )


class _RecordingPersister:
    """Records what the moderator ingests locally, and nothing else."""

    def __init__(self) -> None:
        self.ingested: list[tuple[Any, dict, bool]] = []

    def ingest_local(self, envelope, content, *, list_write=False):
        self.ingested.append((envelope, content, list_write))

    @property
    def pings(self) -> list[tuple[Any, dict]]:
        return [
            (env, content)
            for env, content, _ in self.ingested
            if env.payload.type == l9.PING_PAYLOAD_TYPE
        ]


def _live_room(members: set[str] | None = None):
    """A manager holding one live room whose sends and ingests are observable."""
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

    manager = RoomChannelManager(endpoint="http://127.0.0.1:46357", default_workspace="mycelium")
    channel = MagicMock()
    channel.send = AsyncMock()
    managed = ManagedRoomChannel(
        room=ROOM,
        workspace="mycelium",
        client=MagicMock(),
        channel=channel,
        members=set(members or set()),
    )
    managed.persister = _RecordingPersister()  # type: ignore[assignment]
    manager._channels[ROOM] = managed
    return manager, managed


class TestPing:
    """A thread write surfaces in the room as a signal, never as its content."""

    @pytest.mark.asyncio
    async def test_a_thread_write_leaves_exactly_one_ping_in_live(self):
        """The whole point of the epic's PING: the human's channel shows that a
        unit moved, once, instead of the argument inside it."""
        manager, managed = _live_room()
        await manager.publish_human(
            ROOM, sender="api", text="the token goes in memory", episode=THREAD
        )

        assert len(managed.persister.pings) == 1
        ping, _content = managed.persister.pings[0]
        assert ping.header.message.episode == l9.live_episode_urn(ROOM)
        assert ping.payload.data["episode"] == THREAD

    @pytest.mark.asyncio
    async def test_the_ping_carries_no_echo_of_what_was_said(self):
        manager, managed = _live_room()
        secret = "the token goes in memory"
        await manager.publish_human(ROOM, sender="api", text=secret, episode=THREAD)

        _ping, content = managed.persister.pings[0]
        assert "content" not in content
        assert secret not in json.dumps(content)

    @pytest.mark.asyncio
    async def test_the_ping_names_the_thread_and_the_writer(self):
        manager, managed = _live_room()
        await manager.publish_human(ROOM, sender="api", text="hi", episode=THREAD)

        ping, _content = managed.persister.pings[0]
        assert ping.payload.data["episode"] == THREAD
        assert ping.payload.data["sender"] == "api"
        assert ping.payload.data["message"]  # enough to open the thread on

    @pytest.mark.asyncio
    async def test_the_ping_never_goes_out_on_the_wire(self):
        """Record locally, don't broadcast — the aligner's seam. The channel
        already carried the real message; the ping is for the transcript and GUI."""
        manager, managed = _live_room()
        await manager.publish_human(ROOM, sender="api", text="hi", episode=THREAD)

        sent = [call.args[0] for call in managed.channel.send.call_args_list]
        assert [e for e in sent if e.payload.type == l9.PING_PAYLOAD_TYPE] == []
        assert len(sent) == 1  # the thread message itself, and only that

    @pytest.mark.asyncio
    async def test_the_ping_wakes_nobody(self):
        """A nudge to look, not a turn to take: a resident ``await`` consumes it
        silently rather than spending a reasoning turn on it."""
        manager, managed = _live_room()
        await manager.publish_human(ROOM, sender="api", text="@sec thoughts?", episode=THREAD)

        _ping, content = managed.persister.pings[0]
        assert not participate._addressed_to(content, "sec")
        assert not participate._addressed_to(content, "api")

    @pytest.mark.asyncio
    async def test_a_message_to_the_room_pings_nothing(self):
        manager, managed = _live_room()
        await manager.publish_human(ROOM, sender="api", text="hi")
        await manager.publish_human(
            ROOM, sender="api", text="hi", episode=l9.live_episode_urn(ROOM)
        )
        assert managed.persister.pings == []

    @pytest.mark.asyncio
    async def test_a_thread_message_still_rides_the_channel_normally(self):
        """A thread is a tag over the room's own channel, not a second one."""
        manager, managed = _live_room()
        await manager.publish_human(ROOM, sender="api", text="hi", episode=THREAD)

        sent = [call.args[0] for call in managed.channel.send.call_args_list]
        assert sent[0].header.message.episode == THREAD


class TestWriteRoutes:
    """The two write surfaces take a thread target, and refuse the same way."""

    @pytest.fixture
    async def room(self, client):
        assert (await client.post("/api/rooms", json={"name": ROOM})).status_code in (200, 201)
        return ROOM

    @pytest.mark.asyncio
    async def test_posting_into_an_invented_thread_is_refused(self, client, room):
        """A URN is not a way to open a thread — otherwise the transcript grows
        threads nobody created, each one unreachable from any board row."""
        resp = await client.post(
            f"/api/rooms/{room}/messages",
            json={
                "message_type": "broadcast",
                "sender_handle": "api",
                "content": "hi",
                "episode": THREAD,
            },
        )
        assert resp.status_code == 404
        assert "t3" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_a_refused_post_stores_nothing(self, client, room):
        await client.post(
            f"/api/rooms/{room}/messages",
            json={
                "message_type": "broadcast",
                "sender_handle": "api",
                "content": "hi",
                "episode": THREAD,
            },
        )
        listed = await client.get(f"/api/rooms/{room}/messages")
        assert listed.json()["messages"] == []

    @pytest.mark.asyncio
    async def test_posting_into_a_units_thread_lands_on_that_thread(
        self, client, room, monkeypatch
    ):
        monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
        unit = await units.create_unit(room, "ship passkey login", created_by="avery")
        thread = unit.episode
        assert thread, "a unit is created with its thread already minted"

        resp = await client.post(
            f"/api/rooms/{room}/messages",
            json={
                "message_type": "broadcast",
                "sender_handle": "api",
                "content": "starting on this",
                "episode": thread,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["episode"] == thread

    @pytest.mark.asyncio
    async def test_a_thread_read_filter_answers_the_thread_write(self, client, room, monkeypatch):
        """Write-then-read round-trips on the same URN, which is what makes a board
        row openable as a conversation."""
        monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
        unit = await units.create_unit(room, "rotate the signing key", created_by="avery")
        thread = unit.episode

        await client.post(
            f"/api/rooms/{room}/messages",
            json={
                "message_type": "broadcast",
                "sender_handle": "api",
                "content": "in the thread",
                "episode": thread,
            },
        )
        await client.post(
            f"/api/rooms/{room}/messages",
            json={"message_type": "broadcast", "sender_handle": "api", "content": "in the room"},
        )

        in_thread = await client.get(f"/api/rooms/{room}/messages", params={"episode": thread})
        assert [m["content"] for m in in_thread.json()["messages"]] == ["in the thread"]

        # And the inverse, which is what a legible main channel is read with: the
        # room without its threads. A row posted with no thread carries the
        # ``live`` URN rather than a bare null, so this filter is answerable.
        in_room = await client.get(
            f"/api/rooms/{room}/messages", params={"episode": l9.live_episode_urn(room)}
        )
        assert [m["content"] for m in in_room.json()["messages"]] == ["in the room"]

    @pytest.mark.asyncio
    async def test_an_amendment_stays_in_the_thread_it_revises(self, client, room, monkeypatch):
        """Revising a thread message must not republish its prose to the room —
        the one thing a thread exists to prevent — and the thread's own read has
        to show the revision it folded in."""
        monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
        unit = await units.create_unit(room, "pick a token store", created_by="avery")
        thread = unit.episode

        posted = await client.post(
            f"/api/rooms/{room}/messages",
            json={
                "message_type": "broadcast",
                "sender_handle": "api",
                "content": "in memory",
                "episode": thread,
            },
        )
        amended = await client.post(
            f"/api/rooms/{room}/messages/{posted.json()['id']}/amend",
            json={"sender_handle": "api", "content": "in the keychain"},
        )
        assert amended.status_code == 201
        assert amended.json()["episode"] == thread

        in_thread = await client.get(f"/api/rooms/{room}/messages", params={"episode": thread})
        assert [m["content"] for m in in_thread.json()["messages"]] == ["in the keychain"]

        in_room = await client.get(
            f"/api/rooms/{room}/messages", params={"episode": l9.live_episode_urn(room)}
        )
        assert in_room.json()["messages"] == []
        assert "keychain" not in json.dumps(in_room.json())
