# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the coordination health surface (D3).

The ``/health`` endpoint's ``coordination`` block is how "is the fabric actually
working" becomes answerable in one GET (H1). This pins its shape and the per-room
counters that make channel provisioning, missed-message re-serves, and drops
visible — signals the persister tracks but that were previously log-only.
"""

import pytest

from app.services import persister as persister_mod
from app.services.room_channels import ManagedRoomChannel, manager

_PROCESS_COUNTERS = {"provisions_ok", "provisions_failed", "invite_failures"}
_PER_ROOM_COUNTERS = {
    "reserves",
    "reserve_failures",
    "reserve_skipped",
    "receive_errors",
    "transient_errors",
}


def test_status_exposes_process_and_per_room_counters():
    """manager.status() carries the process provisioning counters and, for each
    room, the full per-room re-serve/drop counter set the health surface needs."""
    room = "health-surface-room"
    p = persister_mod.RoomPersister(
        room,
        channel=None,  # ty: ignore[invalid-argument-type]  # not exercised
        members_provider=lambda: {"a", "b"},
        feed_bus=False,
    )
    # Simulate some history the health surface should report.
    p.reserves = 3
    p.reserve_failures = 1
    p.reserve_skipped = 2
    p.receive_errors = 1
    p.transient_errors = 5

    managed = ManagedRoomChannel(room=room, workspace="ws-1", client=None, channel=None)  # type: ignore[arg-type]
    managed.persister = p
    manager._channels[room] = managed
    try:
        status = manager.status()
        assert status.keys() >= _PROCESS_COUNTERS
        rooms = {r["room"]: r for r in status["rooms"]}
        assert room in rooms
        entry = rooms[room]
        assert entry.keys() >= _PER_ROOM_COUNTERS
        assert entry["reserves"] == 3
        assert entry["reserve_failures"] == 1
        assert entry["reserve_skipped"] == 2
        assert entry["receive_errors"] == 1
        assert entry["transient_errors"] == 5
    finally:
        manager._channels.pop(room, None)


def test_per_room_counters_default_to_zero_without_a_persister():
    """A provisioned room whose persister isn't attached yet still reports the
    counter keys (as 0), so the surface shape is stable for consumers."""
    room = "no-persister-room"
    managed = ManagedRoomChannel(room=room, workspace="ws-1", client=None, channel=None)  # type: ignore[arg-type]
    manager._channels[room] = managed
    try:
        entry = next(r for r in manager.status()["rooms"] if r["room"] == room)
        assert entry.keys() >= _PER_ROOM_COUNTERS
        assert all(entry[k] == 0 for k in _PER_ROOM_COUNTERS)
    finally:
        manager._channels.pop(room, None)


@pytest.mark.asyncio
async def test_health_endpoint_includes_the_coordination_block(client):
    """GET /health surfaces the coordination fabric block with process counters."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    coordination = resp.json()["coordination"]
    assert coordination.keys() >= _PROCESS_COUNTERS
    assert "channels_live" in coordination
    assert isinstance(coordination["rooms"], list)
