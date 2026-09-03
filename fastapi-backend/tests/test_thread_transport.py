# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Writing into a thread, waking on one, and the ping that surfaces it (#837).

A task's thread is a tag over the room's own channel, so the transport
that reaches it is the room's transport with one field on it. These tests hold
the three things that field has to be worth: a write can be *targeted* at a
thread and is refused when it may not be, a wake can be *scoped* to one without
eating the room inbox behind it, and a thread write leaves the room itself
carrying a ping — a signal that a task moved, never an echo of what was said.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from app.routes import participate
from app.services import l9, persister, room_channels, tasks
from app.services.filesystem import get_room_dir
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content

ROOM = "threaded"
THREAD = l9.episode_urn(ROOM, "t3")
OTHER_THREAD = l9.episode_urn(ROOM, "t9")

_REQUEST = Request({"type": "http", "method": "GET", "path": "/await", "headers": []})


async def _unit_thread(room: str, title: str) -> str:
    """Create a task and hand back the thread it was minted with."""
    task = await tasks.create_task(room, title, created_by="avery")
    assert task.episode, "a task is created with its thread already minted"
    return task.episode


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
        """Scoping to a task is the whole point: the room's noise stays out."""
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

        An agent that spends a turn on a task still has its room mentions waiting
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


class TestBareAwaitSeesThreads:
    """A bare (unscoped) ``await`` still wakes on a thread tick.

    ``await``'s own contract (see its docstring) promises a wake on "anything
    addressed to the handle anywhere in the room" when no ``episode`` is given.
    A negotiation always runs inside its own freshly-minted thread — never the
    room's live episode — so excluding thread records from the unscoped path
    (as a prior fix briefly did) left every such tick permanently undeliverable
    to a caller with no live SLIM socket (the plain HTTP long-poll participant
    this endpoint exists for): it has no way to learn the thread's URN ahead of
    time to scope to it.
    """

    @pytest.mark.asyncio
    async def test_a_bare_await_delivers_a_thread_tick(self, wired):
        log = persister.DeliveryLog()
        log.record(_record("t-1", to="api", episode=THREAD), delivered_to=set(), recipients=["api"])

        wired(log)
        result = await participate.await_message(ROOM, _REQUEST, handle="api", timeout=0)
        assert result["message_id"] == "t-1"
        assert result["episode"] == THREAD

    @pytest.mark.asyncio
    async def test_a_bare_delivery_is_not_served_again_scoped(self, wired):
        """Once delivered room-wide, a later ``--task`` scope to the same thread
        must not see it again. No explicit fork is needed to get this: the bare
        delivery advances the room-wide cursor to right past the record, and an
        un-forked thread's position defaults to that same room-wide one
        (``EpisodeCursors.position``'s own contract), so the scoped read lands
        past it for free."""
        log = persister.DeliveryLog()
        log.record(_record("t-1", to="api", episode=THREAD), delivered_to=set(), recipients=["api"])

        fake = wired(log)
        bare = await participate.await_message(ROOM, _REQUEST, handle="api", timeout=0)
        assert bare["message_id"] == "t-1"

        again_scoped = await participate.await_message(
            ROOM, _REQUEST, handle="api", timeout=1, episode=THREAD
        )
        assert again_scoped["message"] is None
        assert fake.episode_position("api", THREAD) == 1

    @pytest.mark.asyncio
    async def test_a_thread_served_scoped_first_is_not_served_again_bare(self, wired):
        """The reverse order of the test above: a ``--task``-scoped read never
        advances the room cursor (on purpose, that's the whole point of the two
        cursors being independent) — so a later bare call, scanning from that
        same untouched room position, must not hand the same record out again."""
        log = persister.DeliveryLog()
        log.record(_record("t-1", to="api", episode=THREAD), delivered_to=set(), recipients=["api"])

        wired(log)
        scoped = await participate.await_message(
            ROOM, _REQUEST, handle="api", timeout=0, episode=THREAD
        )
        assert scoped["message_id"] == "t-1"

        bare = await participate.await_message(ROOM, _REQUEST, handle="api", timeout=1)
        assert bare["message"] is None


class TestThreadWriteAuthorization:
    """Naming a thread is not how one comes into being, and a frozen roster holds."""

    def test_the_room_itself_is_always_writable(self):
        assert tasks.episode_write_rejection(ROOM, "api", None) is None
        assert tasks.episode_write_rejection(ROOM, "api", l9.live_episode_urn(ROOM)) is None

    def test_an_invented_thread_is_refused(self):
        refusal = tasks.episode_write_rejection(ROOM, "api", THREAD)
        assert refusal is not None
        assert refusal.status == 404

    def test_a_thread_the_room_has_spoken_in_is_writable(self):
        assert tasks.episode_write_rejection(ROOM, "api", THREAD, transcript={THREAD}) is None

    def test_a_bound_row_makes_its_thread_writable(self, tmp_path, monkeypatch):
        """A task's thread is writable from the moment the row carries it — before
        anything has been said in it, which is exactly when the first write lands."""
        monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
        get_room_dir(ROOM)
        monkeypatch.setattr(tasks, "bound_episodes", lambda _room: {THREAD})
        assert tasks.episode_write_rejection(ROOM, "api", THREAD) is None

    def test_an_outsider_cannot_drop_a_position_into_a_negotiation(self):
        """L9's stable-membership rule, enforced on the write side: a score across
        a frozen roster means nothing if anyone can post into it."""
        refusal = tasks.episode_write_rejection(
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
            tasks.episode_write_rejection(
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
        """A task outlives what happens inside it, so an agent that claims the row
        after the thread opened can speak in it. The freeze is the negotiation's."""
        assert (
            tasks.episode_write_rejection(
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
        # The write guard reads the transcript to recognize a thread already
        # spoken in; empty here, so every test resolves its thread off the row
        # it is bound to — the first-write path, which is the one that matters.
        self.log = persister.DeliveryLog()

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
    """A thread write surfaces in the room as a signal, never as its content.

    Driven through the write route rather than ``publish_human``, because the
    property is "every write into a thread raises one ping" and the publish
    helper only ever sees one of the ways a write gets there.
    """

    @pytest.fixture
    async def room(self, client, monkeypatch):
        assert (await client.post("/api/rooms", json={"name": ROOM})).status_code in (200, 201)
        monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
        return ROOM

    @pytest.fixture
    def live(self):
        """A live channel for ROOM whose sends and local ingests are observable."""
        manager, managed = _live_room()
        with mock.patch.object(room_channels, "manager", manager):
            yield managed

    @staticmethod
    async def _post(client, *, episode, text="the token goes in memory", kind="broadcast"):
        return await client.post(
            f"/api/rooms/{ROOM}/messages",
            json={
                "message_type": kind,
                "sender_handle": "api",
                "content": text,
                "episode": episode,
            },
        )

    @pytest.mark.asyncio
    async def test_a_thread_write_leaves_exactly_one_ping_in_live(self, client, room, live):
        """The whole point of the epic's PING: the human's channel shows that a
        task moved, once, instead of the argument inside it."""
        thread = await _unit_thread(room, "pick a token store")
        assert (await self._post(client, episode=thread)).status_code == 201

        assert len(live.persister.pings) == 1
        ping, _content = live.persister.pings[0]
        assert ping.header.message.episode == l9.live_episode_urn(ROOM)
        assert ping.payload.data["episode"] == thread

    @pytest.mark.asyncio
    async def test_the_ping_carries_no_echo_of_what_was_said(self, client, room, live):
        thread = await _unit_thread(room, "pick a token store")
        secret = "the token goes in the keychain"
        await self._post(client, episode=thread, text=secret)

        _ping, content = live.persister.pings[0]
        assert "content" not in content
        assert secret not in json.dumps(content)

    @pytest.mark.asyncio
    async def test_the_ping_names_the_thread_and_the_writer(self, client, room, live):
        thread = await _unit_thread(room, "pick a token store")
        await self._post(client, episode=thread)

        ping, _content = live.persister.pings[0]
        assert ping.payload.data["episode"] == thread
        assert ping.payload.data["sender"] == "api"
        assert ping.payload.data["message"]  # enough to open the thread on

    @pytest.mark.asyncio
    async def test_the_ping_never_goes_out_on_the_wire(self, client, room, live):
        """Record locally, don't broadcast — the aligner's seam. The channel
        already carried the real message; the ping is for the transcript and GUI."""
        thread = await _unit_thread(room, "pick a token store")
        await self._post(client, episode=thread)

        sent = [call.args[0] for call in live.channel.send.call_args_list]
        assert [e for e in sent if e.payload.type == l9.PING_PAYLOAD_TYPE] == []
        assert len(sent) == 1  # the thread message itself, and only that
        assert sent[0].header.message.episode == thread  # a tag, not a second channel

    @pytest.mark.asyncio
    async def test_the_ping_wakes_nobody(self, client, room, live):
        """A nudge to look, not a turn to take: a resident ``await`` consumes it
        silently rather than spending a reasoning turn on it."""
        thread = await _unit_thread(room, "pick a token store")
        await self._post(client, episode=thread, text="@sec thoughts?")

        _ping, content = live.persister.pings[0]
        assert not participate._addressed_to(content, "sec")
        assert not participate._addressed_to(content, "api")

    @pytest.mark.asyncio
    async def test_a_message_to_the_room_pings_nothing(self, client, room, live):
        assert (await self._post(client, episode=None)).status_code == 201
        assert (await self._post(client, episode=l9.live_episode_urn(ROOM))).status_code == 201
        assert live.persister.pings == []

    @pytest.mark.asyncio
    async def test_a_write_that_is_not_a_broadcast_still_pings(self, client, room, live):
        """Only a broadcast reaches ``publish_human``. A thread that can be moved
        by an ``announce`` without the room hearing of it is a thread the board
        would show as idle while work happened in it."""
        thread = await _unit_thread(room, "pick a token store")
        assert (await self._post(client, episode=thread, kind="announce")).status_code == 201

        assert len(live.persister.pings) == 1
        assert live.persister.pings[0][0].payload.data["episode"] == thread

    @pytest.mark.asyncio
    async def test_an_amendment_in_a_thread_pings_too(self, client, room, live):
        thread = await _unit_thread(room, "pick a token store")
        posted = await self._post(client, episode=thread, text="in memory")
        live.persister.ingested.clear()

        await client.post(
            f"/api/rooms/{ROOM}/messages/{posted.json()['id']}/amend",
            json={"sender_handle": "api", "content": "in the keychain"},
        )
        assert len(live.persister.pings) == 1

    @pytest.mark.asyncio
    async def test_a_thread_write_with_no_channel_still_reaches_the_bus(self, monkeypatch):
        """A room whose channel is down has no transcript to raise into — so the
        ping matches the reach of the message it announces (bus only) instead of
        vanishing, in the frame a client already decodes."""
        from app.bus import bus, room_channel
        from app.services.room_channels import RoomChannelManager

        published: list[tuple[str, dict]] = []
        monkeypatch.setattr(bus, "publish", lambda ch, frame: published.append((ch, frame)))

        manager = RoomChannelManager(endpoint="http://127.0.0.1:46357", default_workspace="m")
        mid = await manager.raise_ping(ROOM, episode=THREAD, sender="api", message_id="m1")

        assert mid is not None
        assert len(published) == 1
        channel, frame = published[0]
        assert channel == room_channel(ROOM)
        assert frame["message_type"] == "l9_exchange"
        assert frame["episode"] == l9.live_episode_urn(ROOM)
        assert THREAD in frame["content"]


class TestReplyTargeting:
    """Where an agent's reply lands, and what it is an answer *to*.

    The route's subtlest path: a resident loop replies where it was asked
    without ever naming a URN, and a caller that does name one gets that thread
    — including the causal edge, which must not follow it across.
    """

    @pytest.fixture
    async def replying(self, client, monkeypatch):
        """A registered agent, a live channel, and a tick already served to it."""
        assert (await client.post("/api/rooms", json={"name": ROOM})).status_code in (200, 201)
        monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
        monkeypatch.setattr(participate.principals, "post_rejection_reason", lambda *a, **k: None)

        manager, managed = _live_room()

        async def _provision(_room, **_kw):
            return managed

        monkeypatch.setattr(manager, "provision", _provision)
        monkeypatch.setattr(manager, "send_as_custodian", AsyncMock(return_value=False))
        monkeypatch.setattr(participate.room_channels, "manager", manager)
        monkeypatch.setattr(room_channels, "manager", manager)
        participate._last_tick.clear()
        return managed

    @staticmethod
    def _woke(episode: str, *, sender: str = "aligner", message_id: str = "tick-1") -> None:
        """Stand the caller where an ``await`` on ``episode`` would have left it."""
        env = l9.build_envelope(
            kind=Kind.exchange,
            episode=episode,
            sender=sender,
            recipients=["api"],
            topic=l9.topic_urn(ROOM),
            message_id=message_id,
            payload_type="message",
        )
        participate._last_tick[(ROOM, "api")] = serialize_content(
            env, extra={"content": "@api where should the token live?"}
        )

    @staticmethod
    def _replied(managed) -> Any:
        """The reply envelope the route recorded.

        Selected by payload type: the moderator also ingests the ping, and a
        ``create_task`` in the test's own setup broadcasts a ``knowledge`` write.
        """
        replies = [
            env for env, _c, _lw in managed.persister.ingested if env.payload.type == "reply"
        ]
        assert len(replies) == 1, "the route records exactly one reply"
        return replies[0]

    async def _reply(self, client, **body) -> Any:
        return await client.post(
            f"/api/rooms/{ROOM}/reply", json={"handle": "api", "text": "in memory", **body}
        )

    @pytest.mark.asyncio
    async def test_a_reply_answers_where_it_was_asked(self, client, replying):
        """The inherit: a resident loop stays threaded without tracking URNs."""
        thread = await _unit_thread(ROOM, "pick a token store")
        self._woke(thread)

        assert (await self._reply(client)).status_code == 200
        env = self._replied(replying)
        assert env.header.message.episode == thread
        assert env.header.message.parents == ["tick-1"]
        assert [a.id for a in env.header.participants.actors] == ["api", "aligner"]

    @pytest.mark.asyncio
    async def test_a_named_thread_beats_the_one_inherited(self, client, replying):
        thread = await _unit_thread(ROOM, "pick a token store")
        other = await _unit_thread(ROOM, "rotate the signing key")
        self._woke(thread)

        assert (await self._reply(client, episode=other)).status_code == 200
        assert self._replied(replying).header.message.episode == other

    @pytest.mark.asyncio
    async def test_a_redirected_reply_drops_the_causal_edge(self, client, replying):
        """A reply carried into another thread is not an answer to the tick that
        woke it. Keeping the parent would splice one thread's message into
        another's chain, which reads back as a conversation nobody had — and
        would leave the tick's sender addressed in a thread they never spoke in."""
        thread = await _unit_thread(ROOM, "pick a token store")
        other = await _unit_thread(ROOM, "rotate the signing key")
        self._woke(thread)

        await self._reply(client, episode=other)
        env = self._replied(replying)
        assert env.header.message.parents == []
        assert [a.id for a in env.header.participants.actors] == ["api", l9.SYSTEM_ACTOR_ID]

    @pytest.mark.asyncio
    async def test_naming_the_same_thread_keeps_the_edge(self, client, replying):
        """Redirecting is what drops the parent, not the act of naming a thread."""
        thread = await _unit_thread(ROOM, "pick a token store")
        self._woke(thread)

        await self._reply(client, episode=thread)
        assert self._replied(replying).header.message.parents == ["tick-1"]

    @pytest.mark.asyncio
    async def test_a_reply_into_a_thread_pings_the_room(self, client, replying):
        thread = await _unit_thread(ROOM, "pick a token store")
        self._woke(thread)

        await self._reply(client)
        assert len(replying.persister.pings) == 1
        assert replying.persister.pings[0][0].payload.data["episode"] == thread

    @pytest.mark.asyncio
    async def test_a_reply_to_the_room_pings_nothing(self, client, replying):
        self._woke(l9.live_episode_urn(ROOM))

        await self._reply(client)
        assert self._replied(replying).header.message.episode == l9.live_episode_urn(ROOM)
        assert replying.persister.pings == []

    @pytest.mark.asyncio
    async def test_a_reply_into_an_invented_thread_is_refused(self, client, replying):
        self._woke(l9.live_episode_urn(ROOM))

        resp = await self._reply(client, episode=THREAD)
        assert resp.status_code == 404
        # Refused before anything was recorded — no reply, and no ping either.
        assert [e for e, _c, _lw in replying.persister.ingested if e.payload.type == "reply"] == []
        assert replying.persister.pings == []

    @pytest.mark.asyncio
    async def test_a_reply_the_roster_refuses_reaches_nobody(self, client, replying):
        """The whole write gate in one property: a reply that may not land in a
        thread is refused *before* it is recorded, so it wakes no one — the
        transcript is the only delivery path, and a refused write never enters it.
        Today the one roster a thread enforces is a frozen negotiation's; whatever
        else comes to hold a thread's floor has to keep this exact shape."""
        thread = await _unit_thread(ROOM, "pick a token store")
        replying.lifecycle.open(thread, {"aligner", "sec"}, negotiation=True)
        self._woke(l9.live_episode_urn(ROOM))

        resp = await self._reply(client, episode=thread)
        assert resp.status_code == 403
        assert "api" in resp.json()["detail"]
        assert [e for e, _c, _lw in replying.persister.ingested if e.payload.type == "reply"] == []
        assert replying.persister.pings == []
        # Nothing went out on the wire either, so no SLIM-connected member saw it.
        sent = [c.args[0] for c in replying.channel.send.call_args_list]
        assert [e for e in sent if e.payload.type == "reply"] == []

    @pytest.mark.asyncio
    async def test_a_member_of_the_roster_replies_as_before(self, client, replying):
        """The gate is a roster, not a lock: the same frozen thread takes a reply
        from a handle that is at the table."""
        thread = await _unit_thread(ROOM, "pick a token store")
        replying.lifecycle.open(thread, {"aligner", "api"}, negotiation=True)
        self._woke(thread)

        assert (await self._reply(client)).status_code == 200
        assert self._replied(replying).header.message.episode == thread

    @pytest.mark.asyncio
    async def test_a_reply_off_the_floor_is_told_to_wait(self, client, replying):
        """A held floor answers the same way a frozen roster does — before
        anything is recorded — but with a 409 that names whose turn it is, so
        a resident loop reads it as "not yet" rather than "not you"."""
        thread = await _unit_thread(ROOM, "pick a token store")
        room_channels.manager.hold_floor(ROOM, thread, holder="conductor", speakers=["sec"])
        self._woke(thread, sender="conductor")

        resp = await self._reply(client)
        assert resp.status_code == 409
        assert "@conductor holds the floor; @sec may speak" in resp.json()["detail"]
        assert [e for e, _c, _lw in replying.persister.ingested if e.payload.type == "reply"] == []
        assert replying.persister.pings == []

    @pytest.mark.asyncio
    async def test_the_handle_given_the_floor_replies(self, client, replying):
        thread = await _unit_thread(ROOM, "pick a token store")
        room_channels.manager.hold_floor(ROOM, thread, holder="conductor", speakers=["api"])
        self._woke(thread, sender="conductor")

        assert (await self._reply(client)).status_code == 200
        assert self._replied(replying).header.message.episode == thread

    @pytest.mark.asyncio
    async def test_a_released_floor_takes_anyone_again(self, client, replying):
        thread = await _unit_thread(ROOM, "pick a token store")
        room_channels.manager.hold_floor(ROOM, thread, holder="conductor", speakers=["sec"])
        room_channels.manager.release_floor(ROOM, thread)
        self._woke(thread, sender="conductor")

        assert (await self._reply(client)).status_code == 200

    @pytest.mark.asyncio
    async def test_the_room_is_open_however_many_floors_are_held(self, client, replying):
        """A floor narrows one thread; the room itself takes every write."""
        thread = await _unit_thread(ROOM, "pick a token store")
        room_channels.manager.hold_floor(ROOM, thread, holder="conductor", speakers=["sec"])
        self._woke(l9.live_episode_urn(ROOM))

        assert (await self._reply(client)).status_code == 200


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
    async def test_posting_off_the_floor_is_refused_the_same_way(self, client, room, monkeypatch):
        """The human write route passes the one gate ``/reply`` does, so a
        ``board send`` into a held thread waits its turn too — which is how a
        human-in-the-loop step works: the runner gives the person the floor."""
        monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
        manager, _managed = _live_room()
        monkeypatch.setattr(room_channels, "manager", manager)
        thread = await _unit_thread(room, "pick a token store")
        manager.hold_floor(room, thread, holder="conductor", speakers=["julia"])

        body = {"message_type": "broadcast", "content": "hi", "episode": thread}
        refused = await client.post(
            f"/api/rooms/{room}/messages", json={**body, "sender_handle": "api"}
        )
        assert refused.status_code == 409
        assert "@conductor holds the floor; @julia may speak" in refused.json()["detail"]

        admitted = await client.post(
            f"/api/rooms/{room}/messages", json={**body, "sender_handle": "julia"}
        )
        assert admitted.status_code == 201

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
        thread = await _unit_thread(room, "ship passkey login")

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
        thread = await _unit_thread(room, "rotate the signing key")

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
        thread = await _unit_thread(room, "pick a token store")

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
