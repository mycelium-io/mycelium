# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the first-class CoordinationSession entity."""

import pytest


@pytest.mark.asyncio
async def test_spawn_creates_coordination_session(client):
    """Spawning a session creates a CoordinationSession entity."""
    await client.post("/api/rooms", json={"name": "p1"})
    spawn = await client.post("/api/rooms/p1/sessions/spawn")
    assert spawn.status_code == 201
    body = spawn.json()
    assert body["parent"] == "p1"
    assert "coordination_session_id" in body
    display_name = body["session_room"]

    # The display name is synthesized — no Room row exists at it.
    resp = await client.get(f"/api/rooms/{display_name}")
    assert resp.status_code == 404

    # First-class entity is reachable on both endpoints.
    coord = await client.get("/api/rooms/p1/sessions/coordination")
    assert coord.status_code == 200
    rows = coord.json()
    assert len(rows) == 1
    assert rows[0]["parent_room_name"] == "p1"
    assert rows[0]["display_name"] == display_name
    assert rows[0]["id"] == body["coordination_session_id"]

    # Top-level resource also returns it.
    top = await client.get("/api/coordination-sessions?parent_room=p1")
    assert top.status_code == 200
    assert top.json()[0]["id"] == body["coordination_session_id"]


@pytest.mark.asyncio
async def test_list_rooms_only_shows_real_rooms(client):
    """GET /api/rooms only returns real rooms — no session display names ever."""
    await client.post("/api/rooms", json={"name": "p2"})
    await client.post("/api/rooms/p2/sessions/spawn")

    resp = await client.get("/api/rooms")
    names = {r["name"] for r in resp.json()}
    assert "p2" in names
    assert not any(":session:" in n for n in names)


@pytest.mark.asyncio
async def test_idempotent_spawn_does_not_duplicate_coordination_session(client):
    """Re-spawning an already-pending session reuses the existing entity."""
    await client.post("/api/rooms", json={"name": "p3"})
    a = await client.post("/api/rooms/p3/sessions/spawn")
    b = await client.post("/api/rooms/p3/sessions/spawn")
    assert a.json()["coordination_session_id"] == b.json()["coordination_session_id"]

    coord = await client.get("/api/rooms/p3/sessions/coordination")
    assert len(coord.json()) == 1


@pytest.mark.asyncio
async def test_coordination_endpoint_404_for_unknown_room(client):
    resp = await client.get("/api/rooms/nope/sessions/coordination")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_top_level_get_by_id(client):
    await client.post("/api/rooms", json={"name": "p4"})
    spawn = await client.post("/api/rooms/p4/sessions/spawn")
    sid = spawn.json()["coordination_session_id"]

    resp = await client.get(f"/api/coordination-sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sid
    assert resp.json()["display_name"].startswith("p4:session:")


@pytest.mark.asyncio
async def test_top_level_state_filter(client):
    await client.post("/api/rooms", json={"name": "p5"})
    await client.post("/api/rooms/p5/sessions/spawn")

    # Newly spawned, idle.
    resp = await client.get("/api/coordination-sessions?state=idle")
    assert any(r["parent_room_name"] == "p5" for r in resp.json())

    resp = await client.get("/api/coordination-sessions?state=agreed,failed")
    assert not any(r["parent_room_name"] == "p5" for r in resp.json())


@pytest.mark.asyncio
async def test_sessions_are_a_subset_of_a_room(client):
    """Filtering by parent_room returns only that room's sessions.

    This is the contract ``mycelium session ls --room <name>`` relies on:
    sessions are scoped under a parent room and never bleed across rooms.
    """
    await client.post("/api/rooms", json={"name": "alpha"})
    await client.post("/api/rooms", json={"name": "beta"})
    await client.post("/api/rooms/alpha/sessions/spawn")
    await client.post("/api/rooms/beta/sessions/spawn")

    alpha_only = (await client.get("/api/coordination-sessions?parent_room=alpha")).json()
    beta_only = (await client.get("/api/coordination-sessions?parent_room=beta")).json()

    assert {s["parent_room_name"] for s in alpha_only} == {"alpha"}
    assert {s["parent_room_name"] for s in beta_only} == {"beta"}
    assert len(alpha_only) == 1
    assert len(beta_only) == 1
    # display_name preserves the parent → session relationship for legacy URLs.
    assert alpha_only[0]["display_name"].startswith("alpha:session:")
    assert beta_only[0]["display_name"].startswith("beta:session:")
