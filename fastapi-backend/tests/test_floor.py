# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The floor: a thread narrowed to whose turn it is, held by backend code.

Node-free. The policy is a value, the manager holds one per thread, and the
one write gate both routes pass reads it — a refused write never reaches the
transcript, so the wake side needs nothing. With no floor held, every rule
here answers exactly as it did before the floor existed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import l9, tasks
from app.services.floor import Floor
from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

ROOM = "floored"
THREAD = l9.episode_urn(ROOM, "t3")
OTHER = l9.episode_urn(ROOM, "t9")


def _manager() -> tuple[RoomChannelManager, ManagedRoomChannel]:
    manager = RoomChannelManager(endpoint="http://127.0.0.1:46357", default_workspace="mycelium")
    channel = MagicMock()
    channel.send = AsyncMock()
    managed = ManagedRoomChannel(
        room=ROOM, workspace="mycelium", client=MagicMock(), channel=channel
    )
    manager._channels[ROOM] = managed
    return manager, managed


class TestFloorPolicy:
    def test_the_holder_always_has_the_floor(self):
        assert Floor(THREAD, "conductor").admits("conductor")
        assert Floor(THREAD, "conductor").admits("@Conductor")

    def test_a_session_of_a_speaker_is_the_speaker(self):
        """The floor is given to a member; any session of that member holds it."""
        assert Floor(THREAD, "conductor", frozenset({"api"})).admits("api#a8f3")
        assert Floor(THREAD, "conductor").admits("conductor#b2c4")

    def test_a_speaker_has_it_and_nobody_else_does(self):
        floor = Floor(THREAD, "conductor", frozenset({"api"}))
        assert floor.admits("api")
        assert not floor.admits("sec")
        assert not floor.admits("")

    def test_the_refusal_names_who_holds_it_and_who_may_speak(self):
        assert Floor(THREAD, "conductor", frozenset({"sec", "api"})).describe() == (
            "@conductor holds the floor; @api, @sec may speak"
        )
        assert Floor(THREAD, "conductor").describe() == (
            "@conductor holds the floor; no one else may speak right now"
        )


class TestHoldingTheFloor:
    def test_a_room_with_no_channel_holds_nothing(self):
        manager = RoomChannelManager(endpoint="http://x", default_workspace="mycelium")
        assert manager.hold_floor(ROOM, THREAD, holder="conductor") is None
        assert manager.floor(ROOM, THREAD) is None
        assert manager.release_floor(ROOM, THREAD) is False

    def test_the_room_itself_never_holds_a_floor(self):
        manager, managed = _manager()
        assert manager.hold_floor(ROOM, l9.live_episode_urn(ROOM), holder="conductor") is None
        assert managed.floors == {}

    def test_holding_replaces_and_releasing_opens(self):
        manager, _managed = _manager()
        first = manager.hold_floor(ROOM, THREAD, holder="@Conductor", speakers=["@API", "sec"])
        assert first == Floor(THREAD, "conductor", frozenset({"api", "sec"}))
        assert manager.floor(ROOM, THREAD) == first

        second = manager.hold_floor(ROOM, THREAD, holder="conductor", speakers=["sec"])
        assert manager.floor(ROOM, THREAD) == second
        assert second is not None
        assert second.speakers == frozenset({"sec"})

        assert manager.release_floor(ROOM, THREAD) is True
        assert manager.floor(ROOM, THREAD) is None
        assert manager.release_floor(ROOM, THREAD) is False

    def test_floors_are_per_thread(self):
        """One room, two protocols, two floors — a thread's floor is its own."""
        manager, _managed = _manager()
        manager.hold_floor(ROOM, THREAD, holder="conductor", speakers=["api"])
        manager.hold_floor(ROOM, OTHER, holder="reviewer", speakers=["sec"])
        assert manager.floor(ROOM, THREAD) == Floor(THREAD, "conductor", frozenset({"api"}))
        assert manager.floor(ROOM, OTHER) == Floor(OTHER, "reviewer", frozenset({"sec"}))
        assert manager.floor(ROOM, None) is None


class TestTheWriteGate:
    """The floor joins the two refusals the gate already had, after them."""

    def _refusal(self, handle: str, floor: Floor | None, **kw):
        return tasks.episode_write_rejection(
            ROOM, handle, THREAD, transcript={THREAD}, floor=floor, **kw
        )

    def test_no_floor_changes_nothing(self):
        assert self._refusal("anyone", None) is None

    def test_the_holder_and_the_speakers_write(self):
        floor = Floor(THREAD, "conductor", frozenset({"api"}))
        assert self._refusal("conductor", floor) is None
        assert self._refusal("@API", floor) is None

    def test_everyone_else_is_told_to_wait(self):
        floor = Floor(THREAD, "conductor", frozenset({"api"}))
        refusal = self._refusal("sec", floor)
        assert refusal is not None
        assert refusal.status == 409
        assert "@sec does not have the floor" in refusal.detail
        assert "@conductor holds the floor; @api may speak" in refusal.detail

    def test_another_threads_floor_is_not_this_ones(self):
        assert self._refusal("sec", Floor(OTHER, "conductor", frozenset({"api"}))) is None

    def test_the_room_itself_is_never_floored(self):
        live = l9.live_episode_urn(ROOM)
        floor = Floor(live, "conductor")
        assert tasks.episode_write_rejection(ROOM, "sec", live, floor=floor) is None

    def test_a_frozen_roster_answers_first(self):
        """An outsider to a negotiation is refused as an outsider, whatever the
        floor says: the roster is the stronger rule and its answer is the one
        that tells the writer what it is outside of."""
        refusal = self._refusal(
            "sec",
            Floor(THREAD, "conductor", frozenset({"sec"})),
            frozen_episode=THREAD,
            frozen_members={"api"},
        )
        assert refusal is not None
        assert refusal.status == 403

    def test_an_unknown_thread_is_still_unknown(self):
        refusal = tasks.episode_write_rejection(
            ROOM, "api", THREAD, floor=Floor(THREAD, "conductor", frozenset({"api"}))
        )
        assert refusal is not None
        assert refusal.status == 404


class TestTheLiveGate:
    """``thread_write_refusal`` reads the floor off the room's live channel."""

    @pytest.fixture
    def held(self, monkeypatch):
        from app.services import room_channels

        manager, _managed = _manager()
        monkeypatch.setattr(room_channels, "manager", manager)
        monkeypatch.setattr(tasks, "bound_episodes", lambda _room: {THREAD})
        manager.hold_floor(ROOM, THREAD, holder="conductor", speakers=["api"])
        return manager

    def test_it_refuses_off_the_live_floor(self, held):
        refusal = tasks.thread_write_refusal(ROOM, "sec", THREAD)
        assert refusal is not None
        assert refusal.status == 409

    def test_it_admits_the_speaker(self, held):
        assert tasks.thread_write_refusal(ROOM, "api", THREAD) is None

    def test_releasing_opens_the_thread(self, held):
        held.release_floor(ROOM, THREAD)
        assert tasks.thread_write_refusal(ROOM, "sec", THREAD) is None


class TestTheRoomHears:
    """Whose turn it is is a line in the timeline and a fact on the members read."""

    @pytest.fixture
    def notices(self, monkeypatch):
        raised: list[dict] = []

        async def _raise(self, room, **kw):
            raised.append({"room": room, **kw})

        monkeypatch.setattr(RoomChannelManager, "raise_notice", _raise)
        return raised

    @pytest.mark.asyncio
    async def test_a_floor_that_moves_is_a_notice_and_one_that_does_not_is_silent(self, notices):
        manager, _managed = _manager()
        manager.hold_floor(ROOM, THREAD, holder="conductor")
        manager.hold_floor(ROOM, THREAD, holder="conductor", speakers=["api"])
        manager.hold_floor(ROOM, THREAD, holder="conductor", speakers=["api"])
        manager.release_floor(ROOM, THREAD)
        manager.release_floor(ROOM, THREAD)
        await asyncio.sleep(0)

        assert [n["subkind"] for n in notices] == ["floor", "floor", "floor"]
        assert all(n["key"] == "t3" and n["episode"] == THREAD for n in notices)
        assert notices[0]["by"] == "conductor"
        assert notices[0]["speakers"] == ""
        assert notices[1]["speakers"] == "api"
        assert notices[2]["released"] == "1"

    @pytest.mark.asyncio
    async def test_a_notice_names_the_task_the_thread_belongs_to(self, notices, monkeypatch):
        """A task and its thread are one object, so the timeline says the
        task's name; only a thread no row carries is named by its id."""
        from app.services import tasks
        from app.services.filesystem import get_room_dir

        monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
        get_room_dir(ROOM)
        manager, _managed = _manager()
        task = await tasks.create_task(ROOM, "Rotate the signing key", created_by="julia")
        assert task.episode

        manager.hold_floor(ROOM, task.episode, holder="conductor")
        manager.hold_floor(ROOM, THREAD, holder="conductor")
        await asyncio.sleep(0)

        by_episode = {n["episode"]: n for n in notices}
        assert by_episode[task.episode]["key"] == task.key
        assert by_episode[task.episode]["title"] == "Rotate the signing key"
        assert by_episode[THREAD]["key"] == "t3"
        assert by_episode[THREAD]["title"] is None

    def test_a_floor_held_with_no_loop_running_raises_nothing_and_still_holds(self, notices):
        manager, _managed = _manager()
        assert manager.hold_floor(ROOM, THREAD, holder="conductor", speakers=["api"]) is not None
        assert manager.floor(ROOM, THREAD) is not None
        assert notices == []

    @pytest.mark.asyncio
    async def test_the_members_read_lists_every_floor_held(self, client, monkeypatch):
        from app.services import room_channels

        assert (await client.post("/api/rooms", json={"name": ROOM})).status_code in (200, 201)
        manager, _managed = _manager()
        monkeypatch.setattr(room_channels, "manager", manager)
        manager.hold_floor(ROOM, OTHER, holder="reviewer", speakers=["sec"])
        manager.hold_floor(ROOM, THREAD, holder="conductor", speakers=["api", "julia"])

        resp = await client.get(f"/api/rooms/{ROOM}/sessions/members")
        assert resp.status_code == 200
        assert resp.json()["floors"] == [
            {
                "thread": "t3",
                "episode": THREAD,
                "key": None,
                "title": None,
                "holder": "conductor",
                "speakers": ["api", "julia"],
            },
            {
                "thread": "t9",
                "episode": OTHER,
                "key": None,
                "title": None,
                "holder": "reviewer",
                "speakers": ["sec"],
            },
        ]
        manager.release_floor(ROOM, THREAD)
        manager.release_floor(ROOM, OTHER)
        assert (await client.get(f"/api/rooms/{ROOM}/sessions/members")).json()["floors"] == []
