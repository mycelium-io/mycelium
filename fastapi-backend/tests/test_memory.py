"""
Tests for the persistent memory API.

Note: These tests use SQLite which doesn't support pgvector.
Vector search tests are skipped; CRUD and subscription logic is tested.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_room_with_mode(client: AsyncClient):
    """Test creating a room with async mode."""
    resp = await client.post(
        "/rooms",
        json={
            "name": "test-async-room",
            "mode": "async",
            "is_persistent": True,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-async-room"
    assert data["mode"] == "async"
    assert data["is_persistent"] is True


@pytest.mark.asyncio
async def test_create_room_default_sync(client: AsyncClient):
    """Test that rooms default to sync mode."""
    resp = await client.post("/rooms", json={"name": "test-sync-room"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["mode"] == "sync"
    assert data["is_persistent"] is False


@pytest.mark.asyncio
async def test_create_and_get_memory(client: AsyncClient):
    """Test creating and retrieving a memory."""
    # Create room first
    await client.post("/rooms", json={"name": "mem-test", "mode": "async"})

    # Create memory (skip embedding since SQLite doesn't support vector)
    resp = await client.post(
        "/rooms/mem-test/memory",
        json={
            "items": [
                {
                    "key": "project/status",
                    "value": {"status": "in-progress", "sprint": 5},
                    "created_by": "test-agent",
                    "embed": False,
                }
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 1
    assert data[0]["key"] == "project/status"
    assert data[0]["version"] == 1
    assert data[0]["created_by"] == "test-agent"

    # Get memory
    resp = await client.get("/rooms/mem-test/memory/project/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["value"]["status"] == "in-progress"


@pytest.mark.asyncio
async def test_memory_upsert(client: AsyncClient):
    """Test that writing to the same key increments version."""
    await client.post("/rooms", json={"name": "upsert-test", "mode": "async"})

    # First write
    resp = await client.post(
        "/rooms/upsert-test/memory",
        json={
            "items": [
                {"key": "config/db", "value": "postgres", "created_by": "agent-a", "embed": False}
            ]
        },
    )
    assert resp.status_code == 201
    assert resp.json()[0]["version"] == 1

    # Second write (upsert)
    resp = await client.post(
        "/rooms/upsert-test/memory",
        json={
            "items": [
                {"key": "config/db", "value": "agensgraph", "created_by": "agent-b", "embed": False}
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data[0]["version"] == 2
    assert data[0]["updated_by"] == "agent-b"


@pytest.mark.asyncio
async def test_memory_batch_create(client: AsyncClient):
    """Test batch creating multiple memories."""
    await client.post("/rooms", json={"name": "batch-test", "mode": "async"})

    resp = await client.post(
        "/rooms/batch-test/memory",
        json={
            "items": [
                {
                    "key": "decisions/arch",
                    "value": "monolith",
                    "created_by": "agent-a",
                    "embed": False,
                },
                {
                    "key": "decisions/db",
                    "value": "agensgraph",
                    "created_by": "agent-a",
                    "embed": False,
                },
                {
                    "key": "decisions/lang",
                    "value": "python",
                    "created_by": "agent-b",
                    "embed": False,
                },
            ]
        },
    )
    assert resp.status_code == 201
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_memory_list_with_prefix(client: AsyncClient):
    """Test listing memories with prefix filter."""
    await client.post("/rooms", json={"name": "list-test", "mode": "async"})

    await client.post(
        "/rooms/list-test/memory",
        json={
            "items": [
                {"key": "project/a", "value": "1", "created_by": "a", "embed": False},
                {"key": "project/b", "value": "2", "created_by": "a", "embed": False},
                {"key": "config/x", "value": "3", "created_by": "a", "embed": False},
            ]
        },
    )

    # List all
    resp = await client.get("/rooms/list-test/memory")
    assert len(resp.json()) == 3

    # List with prefix
    resp = await client.get("/rooms/list-test/memory", params={"prefix": "project/"})
    data = resp.json()
    assert len(data) == 2
    assert all(m["key"].startswith("project/") for m in data)


@pytest.mark.asyncio
async def test_memory_delete(client: AsyncClient):
    """Test deleting a memory."""
    await client.post("/rooms", json={"name": "del-test", "mode": "async"})

    await client.post(
        "/rooms/del-test/memory",
        json={
            "items": [{"key": "temp/data", "value": "delete-me", "created_by": "a", "embed": False}]
        },
    )

    resp = await client.delete("/rooms/del-test/memory/temp/data")
    assert resp.status_code == 204

    resp = await client.get("/rooms/del-test/memory/temp/data")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_memory_not_found(client: AsyncClient):
    """Test 404 for non-existent memory."""
    await client.post("/rooms", json={"name": "nf-test", "mode": "async"})

    resp = await client.get("/rooms/nf-test/memory/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_room_not_found_for_memory(client: AsyncClient):
    """Test 404 when room doesn't exist."""
    resp = await client.get("/rooms/nonexistent/memory")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_subscription_crud(client: AsyncClient):
    """Test creating and listing subscriptions."""
    await client.post("/rooms", json={"name": "sub-test", "mode": "async"})

    # Create subscription
    resp = await client.post(
        "/rooms/sub-test/memory/subscribe",
        json={
            "key_pattern": "project/*",
            "subscriber": "agent-a",
        },
    )
    assert resp.status_code == 201
    sub = resp.json()
    assert sub["key_pattern"] == "project/*"
    assert sub["subscriber"] == "agent-a"

    # List subscriptions
    resp = await client.get("/rooms/sub-test/memory/subscriptions")
    assert resp.status_code == 200
    subs = resp.json()
    assert len(subs) == 1

    # Delete subscription
    resp = await client.delete(f"/rooms/sub-test/memory/subscribe/{sub['id']}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await client.get("/rooms/sub-test/memory/subscriptions")
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_async_room_join_no_timer(client: AsyncClient):
    """Test that joining an async room doesn't start the coordination timer."""
    await client.post("/rooms", json={"name": "async-join-test", "mode": "async"})

    resp = await client.post(
        "/rooms/async-join-test/sessions",
        json={
            "agent_handle": "agent-a",
            "intent": "sharing context",
        },
    )
    assert resp.status_code == 201

    # Room should still be idle (no timer started)
    resp = await client.get("/rooms/async-join-test")
    assert resp.json()["coordination_state"] == "idle"


@pytest.mark.asyncio
async def test_synthesize_sync_room_rejected(client: AsyncClient):
    """Test that sync rooms reject synthesis requests."""
    await client.post("/rooms", json={"name": "sync-synth-test", "mode": "sync"})

    resp = await client.post("/rooms/sync-synth-test/synthesize")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_hybrid_room_creation(client: AsyncClient):
    """Test creating a hybrid room with trigger config."""
    resp = await client.post(
        "/rooms",
        json={
            "name": "hybrid-test",
            "mode": "hybrid",
            "trigger_config": {"type": "threshold", "min_contributions": 3},
            "is_persistent": True,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["mode"] == "hybrid"
    assert data["trigger_config"]["type"] == "threshold"
    assert data["trigger_config"]["min_contributions"] == 3


# ── Structured memory (category convention) tests ────────────────────────────


@pytest.mark.asyncio
async def test_structured_memory_categories(client: AsyncClient):
    """Test creating and listing memories with structured category prefixes."""
    await client.post("/rooms", json={"name": "struct-test", "mode": "async"})

    # Create memories across categories
    resp = await client.post(
        "/rooms/struct-test/memory",
        json={
            "items": [
                {
                    "key": "work/cron-setup",
                    "value": {"text": "Created crontab", "category": "work"},
                    "created_by": "agent-a",
                    "embed": False,
                },
                {
                    "key": "status/cron",
                    "value": {"text": "ACTIVE", "category": "status"},
                    "created_by": "agent-a",
                    "embed": False,
                },
                {
                    "key": "decisions/polling-interval",
                    "value": {"text": "5min interval", "category": "decisions"},
                    "created_by": "agent-b",
                    "embed": False,
                },
                {
                    "key": "context/user-goal",
                    "value": {"text": "Monitor ticket availability", "category": "context"},
                    "created_by": "agent-a",
                    "embed": False,
                },
            ]
        },
    )
    assert resp.status_code == 201
    assert len(resp.json()) == 4

    # Filter by each category prefix
    for cat, expected_count in [("work/", 1), ("status/", 1), ("decisions/", 1), ("context/", 1)]:
        resp = await client.get("/rooms/struct-test/memory", params={"prefix": cat})
        data = resp.json()
        assert len(data) == expected_count, f"Expected {expected_count} for {cat}, got {len(data)}"
        assert all(m["key"].startswith(cat) for m in data)


@pytest.mark.asyncio
async def test_structured_memory_upsert_preserves_category(client: AsyncClient):
    """Test that upserting a structured memory preserves the category key."""
    await client.post("/rooms", json={"name": "struct-upsert", "mode": "async"})

    # Initial write
    resp = await client.post(
        "/rooms/struct-upsert/memory",
        json={
            "items": [
                {
                    "key": "status/deploy",
                    "value": {"text": "PENDING", "category": "status"},
                    "created_by": "agent-a",
                    "embed": False,
                }
            ]
        },
    )
    assert resp.json()[0]["version"] == 1

    # Upsert with new status
    resp = await client.post(
        "/rooms/struct-upsert/memory",
        json={
            "items": [
                {
                    "key": "status/deploy",
                    "value": {"text": "ACTIVE", "category": "status"},
                    "created_by": "agent-b",
                    "embed": False,
                }
            ]
        },
    )
    assert resp.json()[0]["version"] == 2
    assert resp.json()[0]["updated_by"] == "agent-b"

    # Verify via prefix filter
    resp = await client.get("/rooms/struct-upsert/memory", params={"prefix": "status/"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["value"]["text"] == "ACTIVE"
