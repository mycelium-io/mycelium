"""Tests for session spawning within namespace rooms."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_join_namespace_auto_spawns_session(client: AsyncClient):
    """Joining a namespace room should auto-spawn a sync session."""
    # Create an async (namespace) room
    resp = await client.post("/rooms", json={"name": "ns-test", "mode": "async"})
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
async def test_join_sync_room_directly(client: AsyncClient):
    """Joining a sync room should join directly, no session spawn."""
    await client.post("/rooms", json={"name": "sync-test", "mode": "sync"})

    resp = await client.post(
        "/rooms/sync-test/sessions",
        json={"agent_handle": "agent-b", "intent": "Direct join"},
    )
    assert resp.status_code == 201
    assert resp.json()["room_name"] == "sync-test"


@pytest.mark.asyncio
async def test_multiple_agents_join_same_session(client: AsyncClient):
    """Multiple agents joining the same namespace should land in the same session."""
    await client.post("/rooms", json={"name": "shared-ns", "mode": "async"})

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
    await client.post("/rooms", json={"name": "spawn-ns", "mode": "async"})

    resp = await client.post("/rooms/spawn-ns/sessions/spawn")
    assert resp.status_code == 201
    data = resp.json()
    assert data["parent"] == "spawn-ns"
    assert data["session_room"].startswith("spawn-ns:session:")


@pytest.mark.asyncio
async def test_spawn_on_sync_room_fails(client: AsyncClient):
    """Cannot spawn sessions on a sync room (not a namespace)."""
    await client.post("/rooms", json={"name": "not-ns", "mode": "sync"})

    resp = await client.post("/rooms/not-ns/sessions/spawn")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_hybrid_mode_rejected(client: AsyncClient):
    """Hybrid mode is no longer accepted."""
    resp = await client.post("/rooms", json={"name": "hybrid-test", "mode": "hybrid"})
    assert resp.status_code == 422  # validation error
