# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Tests for session spawning within namespace rooms."""

import pytest
from httpx import AsyncClient
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Room


@pytest.mark.asyncio
async def test_create_room_without_mode(client: AsyncClient):
    """Creating a room without mode field works — defaults to async namespace."""
    resp = await client.post("/rooms", json={"name": "no-mode-test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["mode"] == "async"
    assert data["is_namespace"] is True
    assert data["is_persistent"] is True


@pytest.mark.asyncio
async def test_join_namespace_auto_spawns_session(client: AsyncClient):
    """Joining a namespace room should auto-spawn a sync session."""
    # Create a room (always a namespace now)
    resp = await client.post("/rooms", json={"name": "ns-test"})
    assert resp.status_code == 201
    assert resp.json()["is_namespace"] is True

    # Join it — should auto-spawn a session
    resp = await client.post(
        "/rooms/ns-test/sessions",
        json={"agent_handle": "agent-a", "intent": "Let's negotiate"},
    )
    assert resp.status_code == 201
    data = resp.json()
    # Should be joined to a session room, not the namespace itself
    assert data["room_name"].startswith("ns-test:session:")


@pytest.mark.asyncio
async def test_multiple_agents_join_same_session(client: AsyncClient):
    """Multiple agents joining the same namespace should land in the same session."""
    await client.post("/rooms", json={"name": "shared-ns"})

    resp1 = await client.post(
        "/rooms/shared-ns/sessions",
        json={"agent_handle": "agent-1", "intent": "First"},
    )
    resp2 = await client.post(
        "/rooms/shared-ns/sessions",
        json={"agent_handle": "agent-2", "intent": "Second"},
    )

    assert resp1.json()["room_name"] == resp2.json()["room_name"]


@pytest.mark.asyncio
async def test_explicit_spawn(client: AsyncClient):
    """Explicitly spawning a session in a namespace."""
    await client.post("/rooms", json={"name": "spawn-ns"})

    resp = await client.post("/rooms/spawn-ns/sessions/spawn")
    assert resp.status_code == 201
    data = resp.json()
    assert data["parent"] == "spawn-ns"
    assert data["session_room"].startswith("spawn-ns:session:")


@pytest.mark.asyncio
async def test_spawn_on_non_namespace_fails(client: AsyncClient):
    """Spawning a session on a non-namespace room should 400."""
    # Create a namespace, then spawn a session (which is non-namespace)
    await client.post("/rooms", json={"name": "parent-ns"})
    resp = await client.post("/rooms/parent-ns/sessions/spawn")
    session_name = resp.json()["session_room"]

    # Try to spawn inside the session room — should fail
    resp = await client.post(f"/rooms/{session_name}/sessions/spawn")
    assert resp.status_code == 400
    assert "namespace" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_session_room_enters_waiting_on_join(client: AsyncClient):
    """Joining a session room should transition it to waiting."""
    await client.post("/rooms", json={"name": "wait-ns"})

    resp = await client.post(
        "/rooms/wait-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )
    session_name = resp.json()["room_name"]

    # Session room should be waiting
    resp = await client.get(f"/rooms/{session_name}")
    assert resp.json()["coordination_state"] == "waiting"
    assert resp.json()["join_deadline"] is not None


@pytest.mark.asyncio
async def test_namespace_stays_idle_after_join(client: AsyncClient):
    """The namespace room should remain idle when agents join."""
    await client.post("/rooms", json={"name": "idle-ns"})

    await client.post(
        "/rooms/idle-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )

    resp = await client.get("/rooms/idle-ns")
    assert resp.json()["coordination_state"] == "idle"


@pytest.mark.asyncio
async def test_new_session_after_complete(client: AsyncClient, db_session: AsyncSession):
    """Completing a session should allow spawning a new one in the same namespace."""
    await client.post("/rooms", json={"name": "multi-session-ns"})

    # First session
    resp = await client.post(
        "/rooms/multi-session-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "round 1"},
    )
    session1 = resp.json()["room_name"]

    # Mark the first session as complete via DB
    await db_session.execute(
        sa_update(Room).where(Room.name == session1).values(coordination_state="complete")
    )
    await db_session.commit()

    # Second join should spawn a NEW session (first is complete)
    resp = await client.post(
        "/rooms/multi-session-ns/sessions",
        json={"agent_handle": "agent-b", "intent": "round 2"},
    )
    session2 = resp.json()["room_name"]

    assert session2 != session1
    assert session2.startswith("multi-session-ns:session:")


@pytest.mark.asyncio
async def test_list_sessions_on_session_room(client: AsyncClient):
    """Listing sessions on a session room returns the joined agents."""
    await client.post("/rooms", json={"name": "list-ns"})

    resp = await client.post(
        "/rooms/list-ns/sessions",
        json={"agent_handle": "alpha", "intent": "first"},
    )
    session_name = resp.json()["room_name"]

    await client.post(
        "/rooms/list-ns/sessions",
        json={"agent_handle": "beta", "intent": "second"},
    )

    resp = await client.get(f"/rooms/{session_name}/sessions")
    data = resp.json()
    assert data["total"] == 2
    handles = {s["agent_handle"] for s in data["sessions"]}
    assert handles == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_session_room_is_not_namespace(client: AsyncClient):
    """Session rooms should have is_namespace=False."""
    await client.post("/rooms", json={"name": "check-ns"})

    resp = await client.post(
        "/rooms/check-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )
    session_name = resp.json()["room_name"]

    resp = await client.get(f"/rooms/{session_name}")
    data = resp.json()
    assert data["is_namespace"] is False
    assert data["parent_namespace"] == "check-ns"
