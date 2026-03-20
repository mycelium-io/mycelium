"""Tests for session spawning within namespace rooms."""

import pytest
from httpx import AsyncClient


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
