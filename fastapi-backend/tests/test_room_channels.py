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
async def test_open_episode_freezes_the_full_roster_not_just_slim(
    manager: room_channels.RoomChannelManager,
) -> None:
    """A lease-only participant (headless HTTP await/respond, never SLIM-invited
    because it never goes through a SLIM join at all) is exactly who a
    negotiation runs with — ``members()``'s own union, which the mediator reads
    to build its participant list. The freeze has to protect that same roster,
    not the narrower SLIM-only set, or a lease-only agent is frozen out of its
    own negotiation the instant it tries to respond.
    """
    managed = await manager.provision("room-a")
    assert managed is not None
    await manager.invite("room-a", "agent-slim")
    manager.refresh_lease("room-a", "agent-http")

    assert manager.open_episode("room-a", "urn:ioc:mycelium:episode:room-a:e1") is True
    assert managed.lifecycle.members == frozenset({"agent-slim", "agent-http"})


@pytest.mark.asyncio
async def test_a_real_slim_join_still_aborts_a_frozen_negotiation(
    manager: room_channels.RoomChannelManager,
) -> None:
    """Freezing on the union must not blunt the abort-on-change rule: a genuine
    SLIM join mid-negotiation still changes the roster and still aborts it."""
    managed = await manager.provision("room-a")
    assert managed is not None
    manager.refresh_lease("room-a", "agent-http")
    assert manager.open_episode("room-a", "urn:ioc:mycelium:episode:room-a:e1") is True
    assert managed.lifecycle.active

    await manager.invite("room-a", "agent-slim")  # a real join mid-negotiation
    assert not managed.lifecycle.active


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
