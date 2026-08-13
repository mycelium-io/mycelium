# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Server-pushed refresh events for top-level state changes.

Room create/delete fan out on the global ``app`` channel; agent leave mirrors
the existing join event on the room channel. The UI subscribes to these so its
room list and agent roster update live instead of waiting on a poll.
"""

import pytest

from app.bus import app_channel, bus, room_channel


def _drain(queue) -> list[dict]:
    out: list[dict] = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


@pytest.mark.asyncio
async def test_create_room_publishes_room_created(client):
    q = bus.subscribe(app_channel())
    try:
        resp = await client.post("/api/rooms", json={"name": "platform-eng", "mas_id": "mas-1"})
        assert resp.status_code == 201
        events = _drain(q)
    finally:
        bus.unsubscribe(app_channel(), q)

    assert {"type": "room_created", "room_name": "platform-eng", "mas_id": "mas-1"}.items() <= (
        events[0].items()
    )


@pytest.mark.asyncio
async def test_delete_room_publishes_room_deleted(client):
    await client.post("/api/rooms", json={"name": "platform-eng"})
    q = bus.subscribe(app_channel())
    try:
        resp = await client.delete("/api/rooms/platform-eng")
        assert resp.status_code == 204
        events = _drain(q)
    finally:
        bus.unsubscribe(app_channel(), q)

    assert events == [{"type": "room_deleted", "room_name": "platform-eng"}]


@pytest.mark.asyncio
async def test_idempotent_recreate_does_not_publish(client):
    await client.post("/api/rooms", json={"name": "platform-eng"})
    q = bus.subscribe(app_channel())
    try:
        resp = await client.post("/api/rooms", json={"name": "platform-eng"})
        assert resp.status_code == 201
        events = _drain(q)
    finally:
        bus.unsubscribe(app_channel(), q)

    assert events == []


@pytest.mark.asyncio
async def test_leave_publishes_coordination_leave(client):
    await client.post("/api/rooms", json={"name": "platform-eng"})
    joined = await client.post(
        "/api/rooms/platform-eng/sessions",
        json={"agent_handle": "alice", "intent": "help"},
    )
    assert joined.status_code == 201
    session_id = joined.json()["id"]

    # Subscribe after the join so we only capture the leave event.
    q = bus.subscribe(room_channel("platform-eng"))
    try:
        resp = await client.delete(f"/api/rooms/platform-eng/sessions/{session_id}")
        assert resp.status_code == 204
        events = _drain(q)
    finally:
        bus.unsubscribe(room_channel("platform-eng"), q)

    leave = next(e for e in events if e.get("type") == "coordination_leave")
    assert leave["room_name"] == "platform-eng"
    assert leave["agent_handle"] == "alice"
