# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for backend-as-moderator channel provisioning (room_channels.py).

Node-free: the SLIM transport is the shared :class:`FakeSlimClient` and the
persister start is stubbed to a no-op, so provisioning, member tracking, the
server-held presence lease, and the episode lifecycle are exercised as pure async
logic. The live-node slices stay in ``test_slim_roundtrip.py`` (guarded on a node).
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from app.config import settings
from app.services import room_channels
from tests.fakes import FakeSession, FakeSlimClient


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> room_channels.RoomChannelManager:
    """A manager wired to the fake transport, with the persister loop stubbed out."""
    monkeypatch.setattr(settings, "SLIM_ENABLED", True)
    monkeypatch.setattr(room_channels, "node_reachable", lambda _endpoint: True)
    monkeypatch.setattr(room_channels, "SlimClient", FakeSlimClient)
    # The durable-inbox persister owns a background loop we don't want in a task
    # test — provisioning/membership is the surface under test here.
    monkeypatch.setattr(room_channels.RoomChannelManager, "_start_persister", lambda self, m: None)
    return room_channels.RoomChannelManager(endpoint="http://node", default_workspace="ws")


@pytest.mark.asyncio
async def test_provision_creates_channel_and_counts_ok(
    manager: room_channels.RoomChannelManager,
) -> None:
    managed = await manager.provision("room-a")

    assert managed is not None
    assert manager.is_live("room-a")
    assert managed.workspace == "ws"
    assert isinstance(managed.client, FakeSlimClient)
    assert manager.status()["provisions_ok"] == 1


@pytest.mark.asyncio
async def test_provision_is_idempotent(manager: room_channels.RoomChannelManager) -> None:
    first = await manager.provision("room-a")
    second = await manager.provision("room-a")
    assert first is second  # same managed channel, not a second provision
    assert manager.status()["provisions_ok"] == 1


@pytest.mark.asyncio
async def test_provision_skips_when_slim_disabled(
    manager: room_channels.RoomChannelManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SLIM_ENABLED", False)
    assert await manager.provision("room-a") is None
    assert not manager.is_live("room-a")


@pytest.mark.asyncio
async def test_provision_skips_when_node_unreachable(
    manager: room_channels.RoomChannelManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(room_channels, "node_reachable", lambda _endpoint: False)
    assert await manager.provision("room-a") is None


@pytest.mark.asyncio
async def test_invite_tracks_membership_and_routes_to_session(
    manager: room_channels.RoomChannelManager,
) -> None:
    managed = await manager.provision("room-a")
    assert managed is not None

    assert await manager.invite("room-a", "agent-a") is True
    assert "agent-a" in managed.members
    # The invite was routed onto the moderated session (fake records it).
    session = cast("FakeSession", managed.channel.session)
    assert len(session.invited) == 1
    # The moderator's own id is never invited.
    assert await manager.invite("room-a", room_channels.BACKEND_AGENT) is False


@pytest.mark.asyncio
async def test_remove_drops_membership(manager: room_channels.RoomChannelManager) -> None:
    managed = await manager.provision("room-a")
    assert managed is not None
    await manager.invite("room-a", "agent-a")

    assert await manager.remove("room-a", "agent-a") is True
    assert "agent-a" not in managed.members
    # Removing an absent member is a no-op failure, not a crash.
    assert await manager.remove("room-a", "ghost") is False


@pytest.mark.asyncio
async def test_members_union_slim_presence_and_lease(
    manager: room_channels.RoomChannelManager,
) -> None:
    await manager.provision("room-a")
    await manager.invite("room-a", "agent-slim")  # client-connected → SLIM presence
    manager.refresh_lease("room-a", "agent-http")  # server-held → presence lease

    assert manager.members("room-a") == ["agent-http", "agent-slim"]


def test_expired_lease_drops_from_membership(
    manager: room_channels.RoomChannelManager,
) -> None:
    # A lease with a zero TTL is immediately stale and must not count as present.
    manager.refresh_lease("room-a", "agent-http", ttl_s=-1.0)
    assert manager.members("room-a") == []


def test_herdr_presence_surfaces_without_joining_roster(
    manager: room_channels.RoomChannelManager,
) -> None:
    # A herdr-only handle appears in presence() (the UI surface) but NOT in
    # members() (the mediator roster) — visible, not a negotiation participant.
    manager.set_herdr_presence("room-a", {"reviewer": "idle"})
    presence = manager.presence("room-a")
    assert presence["reviewer"].kind == "herdr"
    assert presence["reviewer"].status == "idle"
    assert manager.members("room-a") == []


def test_herdr_status_overlays_a_lease_member(
    manager: room_channels.RoomChannelManager,
) -> None:
    # A handle present via lease AND mapped to a live herdr pane keeps its lease
    # kind but gains the herdr status.
    manager.refresh_lease("room-a", "reviewer")
    manager.set_herdr_presence("room-a", {"reviewer": "working"})
    presence = manager.presence("room-a")
    assert presence["reviewer"].kind == "lease"
    assert presence["reviewer"].status == "working"


def test_expired_herdr_presence_drops(
    manager: room_channels.RoomChannelManager,
) -> None:
    # A stopped sync bridge (TTL lapsed) clears the overlay on its own.
    manager.set_herdr_presence("room-a", {"reviewer": "idle"}, ttl_s=-1.0)
    assert "reviewer" not in manager.presence("room-a")


def test_herdr_wake_queue_dedupes_and_releases_idle(
    manager: room_channels.RoomChannelManager,
) -> None:
    manager.set_herdr_presence("room-a", {"reviewer": "idle", "docs": "idle"})
    manager.enqueue_herdr_wake("room-a", "reviewer")
    manager.enqueue_herdr_wake("room-a", "docs")
    # Repeat tags of the same handle collapse to one doorbell (no payload to lose).
    manager.enqueue_herdr_wake("room-a", "reviewer")

    drained = manager.drain_herdr_wakes("room-a")
    assert sorted(w["handle"] for w in drained) == ["docs", "reviewer"]
    # Drain removes released wakes.
    assert manager.drain_herdr_wakes("room-a") == []


def test_herdr_wake_held_until_idle(
    manager: room_channels.RoomChannelManager,
) -> None:
    # The "agent hold": a tag for a busy agent is queued but NOT released until it
    # goes idle — so a mention mid-turn is delivered, not dropped.
    manager.set_herdr_presence("room-a", {"reviewer": "working"})
    manager.enqueue_herdr_wake("room-a", "reviewer")
    assert manager.drain_herdr_wakes("room-a") == []  # held while working

    manager.set_herdr_presence("room-a", {"reviewer": "idle"})  # turn finished
    released = manager.drain_herdr_wakes("room-a")
    assert [w["handle"] for w in released] == ["reviewer"]


def test_a_wake_for_an_agent_on_a_long_turn_waits_for_it_however_long(
    manager: room_channels.RoomChannelManager,
) -> None:
    # Working past the hold time: still held, and delivered when the turn ends.
    manager.set_herdr_presence("room-a", {"reviewer": "working"})
    manager.enqueue_herdr_wake("room-a", "reviewer")
    assert manager.drain_herdr_wakes("room-a", hold_ttl_s=-1.0) == []  # held, not dropped
    manager.set_herdr_presence("room-a", {"reviewer": "idle"})
    released = manager.drain_herdr_wakes("room-a", hold_ttl_s=-1.0)
    assert [w["handle"] for w in released] == ["reviewer"]


def test_herdr_wake_hold_expires_once_nothing_reports_the_agent(
    manager: room_channels.RoomChannelManager,
) -> None:
    # No herdr pane reports it any more: there's nothing to deliver to.
    manager.enqueue_herdr_wake("room-a", "reviewer")
    assert manager.drain_herdr_wakes("room-a", hold_ttl_s=-1.0) == []  # expired, dropped
    manager.set_herdr_presence("room-a", {"reviewer": "idle"})
    assert manager.drain_herdr_wakes("room-a") == []  # gone, not resurrected


def test_herdr_status_lookup(
    manager: room_channels.RoomChannelManager,
) -> None:
    manager.set_herdr_presence("room-a", {"reviewer": "working"})
    assert manager.herdr_status("room-a", "reviewer") == "working"


def test_herdr_title_surfaces_on_presence(
    manager: room_channels.RoomChannelManager,
) -> None:
    # A push carrying the terminal title lands as MemberPresence.title — the
    # roster's "current task" line.
    manager.set_herdr_presence(
        "room-a", {"reviewer": {"status": "working", "title": "Review PR 540"}}
    )
    p = manager.presence("room-a")["reviewer"]
    assert p.status == "working"
    assert p.title == "Review PR 540"
    # The bare-string form still works (status only, no title).
    manager.set_herdr_presence("room-b", {"docs": "idle"})
    d = manager.presence("room-b")["docs"]
    assert d.status == "idle"
    assert d.title is None


def test_pending_herdr_wakes_peeks_without_draining(
    manager: room_channels.RoomChannelManager,
) -> None:
    # The read-only counterpart to drain: a held wake shows as pending and is NOT
    # consumed, so the presence surface can badge it repeatedly.
    manager.set_herdr_presence("room-a", {"reviewer": "working"})
    manager.enqueue_herdr_wake("room-a", "reviewer")
    assert manager.pending_herdr_wakes("room-a") == {"reviewer"}
    # Peeking twice is stable (non-destructive), unlike drain.
    assert manager.pending_herdr_wakes("room-a") == {"reviewer"}
    # Past the hold time it's still pending while a pane reports the agent...
    assert manager.pending_herdr_wakes("room-a", hold_ttl_s=-1.0) == {"reviewer"}
    # ...and excluded once none does, matching what drain would drop.
    manager.set_herdr_presence("room-a", {})
    assert manager.pending_herdr_wakes("room-a", hold_ttl_s=-1.0) == set()


def test_two_machines_pushing_in_turn_keep_both_machines_agents_present(
    manager: room_channels.RoomChannelManager,
) -> None:
    # Each machine's runner pushes only its own agents, every few seconds. Many
    # passes in alternation: neither push removes the other machine's agents.
    for _ in range(20):
        manager.set_herdr_presence("room-a", {"ana-agent": "idle"}, source="laptop-ana")
        manager.set_herdr_presence("room-a", {"ben-agent": "working"}, source="laptop-ben")
        assert manager.herdr_status("room-a", "ana-agent") == "idle"
        assert manager.herdr_status("room-a", "ben-agent") == "working"
    # A machine's own push still replaces its own view: a pane it no longer
    # reports is gone, the other machine's stays.
    manager.set_herdr_presence("room-a", {}, source="laptop-ben")
    assert manager.herdr_status("room-a", "ben-agent") is None
    assert manager.herdr_status("room-a", "ana-agent") == "idle"


def test_a_mention_of_the_other_machines_agent_rings_and_reaches_only_its_runner(
    manager: room_channels.RoomChannelManager,
) -> None:
    manager.set_herdr_presence("room-a", {"ana-agent": "idle"}, source="laptop-ana")
    manager.set_herdr_presence("room-a", {"ben-agent": "idle"}, source="laptop-ben")
    # Ana's runner pushed last, after Ben's: Ben's agent is still rung.
    manager.set_herdr_presence("room-a", {"ana-agent": "idle"}, source="laptop-ana")
    assert manager.ring_asked("room-a", "ben-agent", "mention", sender="ana")
    assert manager.ring_asked("room-a", "ana-agent", "mention", sender="ben")
    # Ana's runner drains first and takes only its own agent's wake; Ben's
    # stays queued for Ben's runner rather than being lost on the wrong machine.
    taken = manager.drain_herdr_wakes("room-a", source="laptop-ana")
    assert [w["handle"] for w in taken] == ["ana-agent"]
    assert manager.pending_herdr_wakes("room-a") == {"ben-agent"}
    taken = manager.drain_herdr_wakes("room-a", source="laptop-ben")
    assert [w["handle"] for w in taken] == ["ben-agent"]
    assert manager.pending_herdr_wakes("room-a") == set()


def test_a_bridge_that_names_no_source_drains_as_before(
    manager: room_channels.RoomChannelManager,
) -> None:
    # An older CLI sends no source: its pushes share one source and its drain
    # takes any wake, as it always did.
    manager.set_herdr_presence("room-a", {"ana-agent": "idle"})
    manager.set_herdr_presence("room-a", {"ben-agent": "idle"}, source="laptop-ben")
    manager.enqueue_herdr_wake("room-a", "ana-agent")
    manager.enqueue_herdr_wake("room-a", "ben-agent")
    assert sorted(w["handle"] for w in manager.drain_herdr_wakes("room-a")) == [
        "ana-agent",
        "ben-agent",
    ]


# Who a message asks is ``asks``'s rule, held end to end in
# ``test_wake_paths_table``; these hold what ringing one does.


def test_a_busy_member_asked_is_held_until_it_is_free(
    manager: room_channels.RoomChannelManager,
) -> None:
    manager.set_herdr_presence("room-a", {"docs": "working"})
    assert manager.ring_asked("room-a", "docs", "mention", sender="reviewer") is True
    assert manager.drain_herdr_wakes("room-a") == []
    assert manager.pending_herdr_wakes("room-a") == {"docs"}


def test_a_handle_with_no_herdr_pane_is_not_rung(
    manager: room_channels.RoomChannelManager,
) -> None:
    # Not ours: it reads the message on its next ``await``.
    assert manager.ring_asked("room-a", "ghost", "mention", sender="reviewer") is False
    assert manager.pending_herdr_wakes("room-a") == set()


def test_an_addressed_turn_rings_a_herdr_member_as_a_turn(
    manager: room_channels.RoomChannelManager,
) -> None:
    manager.set_herdr_presence("room-a", {"agent-1": "idle"})
    assert manager.ring_asked("room-a", "agent-1", "turn") is True
    assert manager.ring_asked("room-a", "ghost", "turn") is False
    [wake] = manager.drain_herdr_wakes("room-a")
    assert wake["handle"] == "agent-1"
    assert wake["reason"] == "turn"


def test_a_row_filed_for_a_herdr_member_rings_it_with_the_row(
    manager: room_channels.RoomChannelManager,
) -> None:
    manager.set_herdr_presence("room-a", {"agent-2": "idle"})
    filed = {"subkind": "filed", "key": "work/repro", "title": "Reproduce it", "for": "agent-2"}
    assert manager.herdr_wake_assigned("room-a", {**filed, "subkind": "claimed"}) is False
    assert manager.herdr_wake_assigned("room-a", {**filed, "for": "ghost"}) is False
    assert manager.herdr_wake_assigned("room-a", filed) is True
    [wake] = manager.drain_herdr_wakes("room-a")
    assert wake == {**wake, "reason": "assigned", "key": "work/repro", "title": "Reproduce it"}


def test_a_turn_outranks_a_pending_mention_but_not_the_other_way(
    manager: room_channels.RoomChannelManager,
) -> None:
    # One doorbell per handle; the more specific reason is the one that rings.
    manager.set_herdr_presence("room-a", {"agent-1": "working"})
    manager.enqueue_herdr_wake("room-a", "agent-1")
    manager.enqueue_herdr_wake("room-a", "agent-1", reason="turn")
    manager.enqueue_herdr_wake("room-a", "agent-1")
    manager.set_herdr_presence("room-a", {"agent-1": "idle"})
    [wake] = manager.drain_herdr_wakes("room-a")
    assert wake["reason"] == "turn"


@pytest.mark.asyncio
async def test_every_notice_reaches_the_notice_hook(
    manager: room_channels.RoomChannelManager,
) -> None:
    heard: list[tuple[str, dict[str, str]]] = []
    manager.on_notice = lambda room, notice: heard.append((room, notice))
    await manager.raise_notice(
        "room-a", subkind="filed", key="work/x", title="X", by="agent-1", **{"for": "agent-2"}
    )
    assert heard == [
        (
            "room-a",
            {"subkind": "filed", "key": "work/x", "title": "X", "by": "agent-1", "for": "agent-2"},
        )
    ]


def test_wake_pending_surfaces_on_presence(
    manager: room_channels.RoomChannelManager,
) -> None:
    # A queued-but-held mention lights up wake_pending on the presence surface so
    # the UI can show "tagged, waking when idle".
    manager.set_herdr_presence("room-a", {"reviewer": "working"})
    manager.enqueue_herdr_wake("room-a", "reviewer")
    presence = manager.presence("room-a")
    assert presence["reviewer"].wake_pending is True
    # No wake queued → flag stays False.
    manager.set_herdr_presence("room-b", {"docs": "idle"})
    assert manager.presence("room-b")["docs"].wake_pending is False
    assert manager.herdr_status("room-a", "nobody") is None


@pytest.mark.asyncio
async def test_open_and_close_episode_lifecycle(
    manager: room_channels.RoomChannelManager,
) -> None:
    managed = await manager.provision("room-a")
    assert managed is not None

    assert manager.open_episode("room-a", "urn:ioc:mycelium:episode:room-a:e1") is True
    assert managed.lifecycle.active
    assert await manager.close_episode("room-a") is True
    assert not managed.lifecycle.active

    # No channel → lifecycle ops are safe no-ops.
    assert manager.open_episode("ghost", "e") is False
    assert await manager.close_episode("ghost") is False


@pytest.mark.asyncio
async def test_open_episode_freezes_the_parties_it_was_given(
    manager: room_channels.RoomChannelManager,
) -> None:
    """A negotiation freezes who it brokers between, not everyone present: in a
    busy room that's how members nobody named were pulled in."""
    managed = await manager.provision("room-a")
    assert managed is not None
    await manager.invite("room-a", "reviewer")
    manager.refresh_lease("room-a", "bystander")

    episode = "urn:ioc:mycelium:episode:room-a:e1"
    assert manager.open_episode("room-a", episode, parties=["@Agent-A", "agent-b"]) is True
    assert managed.lifecycle.members == frozenset({"agent-a", "agent-b"})


async def _settle(manager: room_channels.RoomChannelManager) -> None:
    """Let anything a join schedules run to completion."""
    if manager._tasks:
        await asyncio.gather(*manager._tasks)


@pytest.mark.asyncio
async def test_joins_mid_negotiation_never_abort_it(
    manager: room_channels.RoomChannelManager,
) -> None:
    """Presence coming and going isn't a reason to stop a run (what #932 meant
    to fix): a SLIM join, a brand-new headless caller and a party's own lease
    starting all leave it running."""
    managed = await manager.provision("room-a")
    assert managed is not None
    episode = "urn:ioc:mycelium:episode:room-a:e1"
    assert manager.open_episode("room-a", episode, parties=["agent-a", "agent-b"]) is True

    await manager.invite("room-a", "agent-slim")
    manager.refresh_lease("room-a", "agent-new")
    manager.refresh_lease("room-a", "agent-a")
    await _settle(manager)

    assert managed.lifecycle.active


@pytest.mark.asyncio
async def test_removing_a_party_from_the_room_ends_the_negotiation(
    manager: room_channels.RoomChannelManager,
) -> None:
    """Only a party actually leaving ends it; what it posts is checked in
    ``test_mentions_and_invites``, whose channel records."""
    managed = await manager.provision("room-a")
    assert managed is not None
    await manager.invite("room-a", "agent-a")
    await manager.invite("room-a", "reviewer")
    episode = "urn:ioc:mycelium:episode:room-a:e1"
    assert manager.open_episode("room-a", episode, parties=["agent-a", "agent-b"]) is True

    # Someone who isn't a party leaving changes nothing.
    await manager.remove("room-a", "reviewer")
    assert managed.lifecycle.active

    await manager.remove("room-a", "agent-a")
    assert not managed.lifecycle.active


@pytest.mark.asyncio
async def test_removing_a_party_tells_the_engine_running_the_negotiation(
    manager: room_channels.RoomChannelManager,
) -> None:
    told: list[tuple[str, str, str]] = []
    manager.on_party_left = (
        lambda room, episode, handle: told.append((room, episode, handle)) or True
    )
    managed = await manager.provision("room-a")
    assert managed is not None
    await manager.invite("room-a", "agent-a")
    episode = "urn:ioc:mycelium:episode:room-a:e1"
    manager.open_episode("room-a", episode, parties=["agent-a", "agent-b"])

    await manager.remove("room-a", "agent-a")

    assert told == [("room-a", episode, "agent-a")]


@pytest.mark.asyncio
async def test_a_frozen_participant_refreshing_its_lease_is_not_a_join(
    manager: room_channels.RoomChannelManager,
) -> None:
    """Every ``await`` poll refreshes the lease; only the not-present → present
    edge is a join. A participant holding its lease through the negotiation must
    not abort it."""
    managed = await manager.provision("room-a")
    assert managed is not None
    manager.refresh_lease("room-a", "agent-http")
    assert manager.open_episode("room-a", "urn:ioc:mycelium:episode:room-a:e1") is True

    manager.refresh_lease("room-a", "agent-http")
    manager.refresh_lease("room-a", "agent-http")
    await _settle(manager)

    assert managed.lifecycle.active
    assert not manager._tasks  # nothing was even scheduled


@pytest.mark.asyncio
async def test_a_lease_only_join_leaves_a_task_thread_running(
    manager: room_channels.RoomChannelManager,
) -> None:
    """A task's thread is a container, not a negotiation: someone arriving must
    not end it, from the lease side any more than from the SLIM side."""
    managed = await manager.provision("room-a")
    assert managed is not None
    manager.refresh_lease("room-a", "agent-http")
    assert (
        manager.open_episode("room-a", "urn:ioc:mycelium:episode:room-a:t1", negotiation=False)
        is True
    )

    manager.refresh_lease("room-a", "agent-new")
    await _settle(manager)

    assert managed.lifecycle.active


@pytest.mark.asyncio
async def test_status_reports_per_room_snapshot(
    manager: room_channels.RoomChannelManager,
) -> None:
    await manager.provision("room-a")
    await manager.invite("room-a", "agent-a")

    status = manager.status()
    assert status["channels_live"] == 1
    room = next(r for r in status["rooms"] if r["room"] == "room-a")
    assert room["provisioned"] is True
    assert room["members"] == ["agent-a"]


@pytest.mark.asyncio
async def test_persister_members_provider_excludes_lease_only_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persister's ``delivered_to`` source must be real SLIM members only.

    A server-held ``await`` lease is polling, not pushed-to: DeliveryLog.record
    marks anyone in ``delivered_to`` as caught up to the message just recorded,
    so if a lease-only handle were counted, a mention addressed to it would be
    marked delivered before its own poll ever read it — silently un-deliverable.
    ``manager.members(room)`` unions SLIM members with lease holders (correct for
    the roster/mention gate uses), so the persister must be wired to the
    channel's own live SLIM set instead, not that union.
    """
    monkeypatch.setattr(settings, "SLIM_ENABLED", True)
    monkeypatch.setattr(room_channels, "node_reachable", lambda _endpoint: True)
    monkeypatch.setattr(room_channels, "SlimClient", FakeSlimClient)

    class _FakeRoomPersister:
        def __init__(self, room, channel, *, members_provider, **_kw):
            self.members_provider = members_provider

        async def run(self):
            return None

    monkeypatch.setattr(room_channels, "RoomPersister", _FakeRoomPersister)

    manager = room_channels.RoomChannelManager(endpoint="http://node", default_workspace="ws")
    managed = await manager.provision("room-a")
    assert managed is not None
    managed.members.add("slim-agent")
    manager.refresh_lease("room-a", "lease-only-agent")

    # The union (roster/mention gate use) legitimately includes both.
    assert set(manager.members("room-a")) == {"slim-agent", "lease-only-agent"}
    # The persister's delivery source must not.
    fake_persister = cast(_FakeRoomPersister, managed.persister)
    assert fake_persister.members_provider() == {"slim-agent"}


# ── joins are announced once per member ──────────────────────────────────────


def _joins(room: str) -> list[str]:
    import json

    from app.services import in_memory_store

    return [
        json.loads(m.content)["handle"]
        for m in in_memory_store.list_messages(room)
        if m.message_type == "coordination_join"
    ]


@pytest.mark.asyncio
async def test_a_member_is_announced_once_not_on_every_return(
    manager: room_channels.RoomChannelManager,
) -> None:
    from app.services.filesystem import get_room_dir

    get_room_dir("room-j")  # the room exists on disk, as a real one does
    manager.refresh_lease("room-j", "claude")
    # Between turns: the lease lapses, then the next await comes back.
    manager.refresh_lease("room-j", "claude", ttl_s=-1.0)
    manager.members("room-j")
    manager.refresh_lease("room-j", "claude")
    assert _joins("room-j") == ["claude"]

    # A restart forgets nothing: a fresh manager reads who was announced.
    restarted = room_channels.RoomChannelManager(endpoint="http://node", default_workspace="ws")
    restarted.refresh_lease("room-j", "claude")
    assert _joins("room-j") == ["claude"]


@pytest.mark.asyncio
async def test_a_dropped_connection_is_not_a_new_arrival(
    manager: room_channels.RoomChannelManager,
) -> None:
    from app.services.filesystem import get_room_dir

    get_room_dir("room-k")
    await manager.provision("room-k")
    await manager.invite("room-k", "codex")
    manager._drop_member("room-k", "codex")
    await manager.invite("room-k", "codex")
    assert _joins("room-k") == ["codex"]


@pytest.mark.asyncio
async def test_a_member_removed_and_added_again_is_announced_again(
    manager: room_channels.RoomChannelManager,
) -> None:
    from app.services.filesystem import get_room_dir

    get_room_dir("room-r")
    await manager.provision("room-r")
    await manager.invite("room-r", "codex")
    assert await manager.remove("room-r", "codex")
    await manager.invite("room-r", "codex")
    assert _joins("room-r") == ["codex", "codex"]
