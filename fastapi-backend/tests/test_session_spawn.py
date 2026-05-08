# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for coordination session spawning (#197 + #244)."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CoordinationSession


async def _coord_for_room(client: AsyncClient, namespace: str) -> dict:
    """Return the most recent CoordinationSession dict for a namespace room."""
    resp = await client.get(f"/api/rooms/{namespace}/sessions/coordination")
    rows = resp.json()
    assert rows, f"no coordination sessions for {namespace}"
    return rows[0]


@pytest.mark.asyncio
async def test_create_room_defaults(client: AsyncClient):
    """Creating a room defaults to a persistent namespace."""
    resp = await client.post("/api/rooms", json={"name": "no-mode-test"})
    assert resp.status_code == 201
    assert resp.json()["is_persistent"] is True


@pytest.mark.asyncio
async def test_join_namespace_auto_spawns_session(client: AsyncClient):
    """Joining a room auto-spawns a coordination session."""
    await client.post("/api/rooms", json={"name": "ns-test"})

    resp = await client.post(
        "/api/rooms/ns-test/sessions",
        json={"agent_handle": "agent-a", "intent": "Let's negotiate"},
    )
    assert resp.status_code == 201
    coord = await _coord_for_room(client, "ns-test")
    assert resp.json()["coordination_session_id"] == coord["id"]
    assert coord["display_name"].startswith("ns-test:session:")


@pytest.mark.asyncio
async def test_multiple_agents_join_same_session(client: AsyncClient):
    """Multiple agents joining the same room land in the same coord session."""
    await client.post("/api/rooms", json={"name": "shared-ns"})

    resp1 = await client.post(
        "/api/rooms/shared-ns/sessions",
        json={"agent_handle": "agent-1", "intent": "First"},
    )
    resp2 = await client.post(
        "/api/rooms/shared-ns/sessions",
        json={"agent_handle": "agent-2", "intent": "Second"},
    )
    assert resp1.json()["coordination_session_id"] == resp2.json()["coordination_session_id"]


@pytest.mark.asyncio
async def test_explicit_spawn(client: AsyncClient):
    """Explicitly spawning a coordination session."""
    await client.post("/api/rooms", json={"name": "spawn-ns"})

    resp = await client.post("/api/rooms/spawn-ns/sessions/spawn")
    assert resp.status_code == 201
    data = resp.json()
    assert data["parent"] == "spawn-ns"
    assert data["session_room"].startswith("spawn-ns:session:")
    assert "coordination_session_id" in data


@pytest.mark.asyncio
async def test_spawn_on_session_display_404(client: AsyncClient):
    """Spawning under a session display name returns 404 (no real room)."""
    await client.post("/api/rooms", json={"name": "parent-ns"})
    resp = await client.post("/api/rooms/parent-ns/sessions/spawn")
    session_name = resp.json()["session_room"]

    resp = await client.post(f"/api/rooms/{session_name}/sessions/spawn")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_join_transitions_coord_session_to_waiting(client: AsyncClient):
    """Joining transitions the coord session state machine to waiting."""
    await client.post("/api/rooms", json={"name": "wait-ns"})

    await client.post(
        "/api/rooms/wait-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )
    coord = await _coord_for_room(client, "wait-ns")
    assert coord["state"] == "waiting"
    assert coord["join_window_ends_at"] is not None


@pytest.mark.asyncio
async def test_namespace_room_stays_idle_after_join(client: AsyncClient):
    """The room itself stays idle; only the coord session enters waiting."""
    await client.post("/api/rooms", json={"name": "idle-ns"})

    await client.post(
        "/api/rooms/idle-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )

    resp = await client.get("/api/rooms/idle-ns")
    assert resp.json()["coordination_state"] == "idle"


@pytest.mark.asyncio
async def test_new_session_after_complete(client: AsyncClient, db_session: AsyncSession):
    """Completing a session lets a fresh one spawn in the same namespace."""
    await client.post("/api/rooms", json={"name": "multi-session-ns"})

    resp1 = await client.post(
        "/api/rooms/multi-session-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "round 1"},
    )
    coord1_id = resp1.json()["coordination_session_id"]

    await db_session.execute(
        sa_update(CoordinationSession)
        .where(CoordinationSession.id == UUID(coord1_id))
        .values(state="complete")
    )
    await db_session.commit()

    resp2 = await client.post(
        "/api/rooms/multi-session-ns/sessions",
        json={"agent_handle": "agent-b", "intent": "round 2"},
    )
    assert resp2.json()["coordination_session_id"] != coord1_id


@pytest.mark.asyncio
async def test_list_participants_via_session_display_name(client: AsyncClient):
    """List participants by session display name returns the joined agents."""
    await client.post("/api/rooms", json={"name": "list-ns"})

    await client.post(
        "/api/rooms/list-ns/sessions",
        json={"agent_handle": "alpha", "intent": "first"},
    )
    coord = await _coord_for_room(client, "list-ns")
    session_name = coord["display_name"]

    await client.post(
        "/api/rooms/list-ns/sessions",
        json={"agent_handle": "beta", "intent": "second"},
    )

    resp = await client.get(f"/api/rooms/{session_name}/sessions")
    data = resp.json()
    assert data["total"] == 2
    handles = {p["agent_handle"] for p in data["participants"]}
    assert handles == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_session_display_name_is_not_a_room(client: AsyncClient):
    """Session display names no longer have a backing Room row (#244)."""
    await client.post("/api/rooms", json={"name": "check-ns"})

    await client.post(
        "/api/rooms/check-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )
    coord = await _coord_for_room(client, "check-ns")
    session_name = coord["display_name"]

    # /api/rooms/{display_name} 404s because shadow rows are gone.
    resp = await client.get(f"/api/rooms/{session_name}")
    assert resp.status_code == 404
