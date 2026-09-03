# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The floor: a thread narrowed to whose turn it is, held by backend code.

Node-free. The policy is a value, the manager holds one per thread, and the
one write gate both routes pass reads it — a refused write never reaches the
transcript, so the wake side needs nothing. With no floor held, every rule
here answers exactly as it did before the floor existed.
"""

from __future__ import annotations

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
