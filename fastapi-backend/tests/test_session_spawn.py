# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for session spawning within namespace rooms."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CoordinationSession, Room


async def _coord_for_room(client: AsyncClient, namespace: str) -> dict:
    """Return the most recent CoordinationSession dict for a namespace room."""
    resp = await client.get(f"/api/rooms/{namespace}/sessions/coordination")
    rows = resp.json()
    assert rows, f"no coordination sessions for {namespace}"
    return rows[0]


@pytest.mark.asyncio
async def test_create_room_without_mode(client: AsyncClient):
    """Creating a room without mode field works — defaults to async namespace."""
    resp = await client.post("/api/rooms", json={"name": "no-mode-test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["mode"] == "async"
    assert data["is_namespace"] is True
    assert data["is_persistent"] is True


@pytest.mark.asyncio
async def test_join_namespace_auto_spawns_session(client: AsyncClient):
    """Joining a namespace room should auto-spawn a sync session."""
    resp = await client.post("/api/rooms", json={"name": "ns-test"})
    assert resp.status_code == 201
    assert resp.json()["is_namespace"] is True

    resp = await client.post(
        "/api/rooms/ns-test/sessions",
        json={"agent_handle": "agent-a", "intent": "Let's negotiate"},
    )
    assert resp.status_code == 201
    data = resp.json()
    # Participant has a coordination_session_id — the entity it joined.
    coord = await _coord_for_room(client, "ns-test")
    assert data["coordination_session_id"] == coord["id"]
    assert coord["display_name"].startswith("ns-test:session:")


@pytest.mark.asyncio
async def test_multiple_agents_join_same_session(client: AsyncClient):
    """Multiple agents joining the same namespace should land in the same session."""
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
    """Explicitly spawning a session in a namespace."""
    await client.post("/api/rooms", json={"name": "spawn-ns"})

    resp = await client.post("/api/rooms/spawn-ns/sessions/spawn")
    assert resp.status_code == 201
    data = resp.json()
    assert data["parent"] == "spawn-ns"
    assert data["session_room"].startswith("spawn-ns:session:")


@pytest.mark.asyncio
async def test_spawn_on_non_namespace_fails(client: AsyncClient):
    """Spawning a session on a non-namespace room should 400."""
    await client.post("/api/rooms", json={"name": "parent-ns"})
    resp = await client.post("/api/rooms/parent-ns/sessions/spawn")
    session_name = resp.json()["session_room"]

    resp = await client.post(f"/api/rooms/{session_name}/sessions/spawn")
    assert resp.status_code == 400
    assert "namespace" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_session_room_enters_waiting_on_join(client: AsyncClient):
    """Joining a session room should transition it to waiting."""
    await client.post("/api/rooms", json={"name": "wait-ns"})

    await client.post(
        "/api/rooms/wait-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )
    coord = await _coord_for_room(client, "wait-ns")
    session_name = coord["display_name"]

    resp = await client.get(f"/api/rooms/{session_name}")
    assert resp.json()["coordination_state"] == "waiting"
    assert resp.json()["join_deadline"] is not None


@pytest.mark.asyncio
async def test_namespace_stays_idle_after_join(client: AsyncClient):
    """The namespace room should remain idle when agents join."""
    await client.post("/api/rooms", json={"name": "idle-ns"})

    await client.post(
        "/api/rooms/idle-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )

    resp = await client.get("/api/rooms/idle-ns")
    assert resp.json()["coordination_state"] == "idle"


@pytest.mark.asyncio
async def test_new_session_after_complete(client: AsyncClient, db_session: AsyncSession):
    """Completing a session should allow spawning a new one in the same namespace."""
    await client.post("/api/rooms", json={"name": "multi-session-ns"})

    resp1 = await client.post(
        "/api/rooms/multi-session-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "round 1"},
    )
    coord1_id = resp1.json()["coordination_session_id"]
    coord1 = await _coord_for_room(client, "multi-session-ns")
    session1 = coord1["display_name"]

    # Mark first session as complete via DB shadow row + coord_session row.
    await db_session.execute(
        sa_update(Room).where(Room.name == session1).values(coordination_state="complete")
    )
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
    coord2_id = resp2.json()["coordination_session_id"]
    assert coord2_id != coord1_id


@pytest.mark.asyncio
async def test_list_sessions_on_session_room(client: AsyncClient):
    """Listing participants on a session-shadow room returns the joined agents."""
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
async def test_session_room_is_not_namespace(client: AsyncClient):
    """Session-shadow rooms should have is_namespace=False."""
    await client.post("/api/rooms", json={"name": "check-ns"})

    await client.post(
        "/api/rooms/check-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )
    coord = await _coord_for_room(client, "check-ns")
    session_name = coord["display_name"]

    resp = await client.get(f"/api/rooms/{session_name}")
    data = resp.json()
    assert data["is_namespace"] is False
    assert data["parent_namespace"] == "check-ns"
