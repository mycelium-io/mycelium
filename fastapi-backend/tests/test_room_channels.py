# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for backend-as-moderator channel provisioning (room_channels.py).

Node-free: the SLIM transport is the shared :class:`FakeSlimClient` and the
persister start is stubbed to a no-op, so provisioning, member tracking, the
server-held presence lease, and the episode lifecycle are exercised as pure async
logic. The live-node slices stay in ``test_slim_roundtrip.py`` (guarded on a node).
"""

from __future__ import annotations

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
    # The durable-inbox persister owns a background loop we don't want in a unit
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


def test_herdr_wake_hold_expires(
    manager: room_channels.RoomChannelManager,
) -> None:
    # A never-idle agent doesn't hold a tag forever.
    manager.set_herdr_presence("room-a", {"reviewer": "working"})
    manager.enqueue_herdr_wake("room-a", "reviewer")
    assert manager.drain_herdr_wakes("room-a", hold_ttl_s=-1.0) == []  # expired, dropped
    manager.set_herdr_presence("room-a", {"reviewer": "idle"})
    assert manager.drain_herdr_wakes("room-a") == []  # gone, not resurrected


def test_herdr_status_lookup(
    manager: room_channels.RoomChannelManager,
) -> None:
    manager.set_herdr_presence("room-a", {"reviewer": "working"})
    assert manager.herdr_status("room-a", "reviewer") == "working"
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
