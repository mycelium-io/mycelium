# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for the first-class CoordinationSession entity (#197)."""

import pytest


@pytest.mark.asyncio
async def test_spawn_creates_coordination_session_row(client):
    """Spawning a session writes a CoordinationSession alongside the shadow Room."""
    await client.post("/api/rooms", json={"name": "p1"})
    spawn = await client.post("/api/rooms/p1/sessions/spawn")
    assert spawn.status_code == 201
    session_room_name = spawn.json()["session_room"]

    # Shadow Room row still exists for FK compat with messages/memory.
    shadow = await client.get(f"/api/rooms/{session_room_name}")
    assert shadow.status_code == 200
    assert shadow.json()["parent_namespace"] == "p1"

    # First-class entity exists at the new endpoint.
    coord = await client.get("/api/rooms/p1/sessions/coordination")
    assert coord.status_code == 200
    rows = coord.json()
    assert len(rows) == 1
    assert rows[0]["parent_room_name"] == "p1"
    assert rows[0]["display_name"] == session_room_name


@pytest.mark.asyncio
async def test_list_rooms_hides_session_shadows_by_default(client):
    """GET /api/rooms excludes session-shadow rows unless asked."""
    await client.post("/api/rooms", json={"name": "p2"})
    await client.post("/api/rooms/p2/sessions/spawn")

    default = await client.get("/api/rooms")
    names_default = {r["name"] for r in default.json()}
    assert "p2" in names_default
    assert not any(":session:" in n for n in names_default)

    included = await client.get("/api/rooms?include_sessions=true")
    names_included = {r["name"] for r in included.json()}
    assert "p2" in names_included
    assert any(":session:" in n for n in names_included)


@pytest.mark.asyncio
async def test_idempotent_spawn_does_not_duplicate_coordination_session(client):
    """Re-spawning an already-pending session reuses the existing entity."""
    await client.post("/api/rooms", json={"name": "p3"})
    a = await client.post("/api/rooms/p3/sessions/spawn")
    b = await client.post("/api/rooms/p3/sessions/spawn")
    assert a.json()["session_room"] == b.json()["session_room"]

    coord = await client.get("/api/rooms/p3/sessions/coordination")
    assert len(coord.json()) == 1


@pytest.mark.asyncio
async def test_coordination_endpoint_404_for_unknown_room(client):
    resp = await client.get("/api/rooms/nope/sessions/coordination")
    assert resp.status_code == 404
