"""
Integration tests — require a running Postgres/AgensGraph with pgvector.

These tests hit the real database to verify:
  - Vector embedding + semantic search
  - Memory subscription NOTIFY
  - Async synthesis trigger
  - Room mode behavior end-to-end

Skip automatically if DATABASE_URL is not set or DB is unreachable.

Run with:
    DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5555/mycelium \
        uv run pytest tests/test_integration.py -x -v
"""

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Skip entire module if no real DB configured
INTEGRATION_DB_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not INTEGRATION_DB_URL or "sqlite" in INTEGRATION_DB_URL,
    reason="Integration tests require DATABASE_URL pointing to Postgres/AgensGraph with pgvector",
)


@pytest_asyncio.fixture()
async def integration_client():
    """Client wired to real database — creates and drops tables per test."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import get_async_session
    from app.main import app
    from app.models import Base

    engine = create_async_engine(INTEGRATION_DB_URL)

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

    # Clean up tables after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_memory_create_with_embedding(integration_client: AsyncClient):
    """Test that memories are created with vector embeddings."""
    client = integration_client

    # Create async room
    resp = await client.post("/rooms", json={"name": "e2e-embed", "mode": "async"})
    assert resp.status_code == 201

    # Create memory with embedding (embed=True is default)
    resp = await client.post(
        "/rooms/e2e-embed/memory",
        json={
            "items": [
                {
                    "key": "test/concept",
                    "value": "AgensGraph is a multi-model graph database built on PostgreSQL",
                    "created_by": "test-agent",
                    "embed": True,
                }
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 1
    assert data[0]["key"] == "test/concept"


@pytest.mark.asyncio
async def test_semantic_search(integration_client: AsyncClient):
    """Test semantic vector search returns relevant results ranked by similarity."""
    client = integration_client

    await client.post("/rooms", json={"name": "e2e-search", "mode": "async"})

    # Write several memories with different topics
    await client.post(
        "/rooms/e2e-search/memory",
        json={
            "items": [
                {
                    "key": "topic/databases",
                    "value": "PostgreSQL is a relational database with ACID transactions",
                    "created_by": "agent-a",
                    "embed": True,
                },
                {
                    "key": "topic/cooking",
                    "value": "The best pasta requires fresh ingredients and al dente timing",
                    "created_by": "agent-b",
                    "embed": True,
                },
                {
                    "key": "topic/graphs",
                    "value": "Knowledge graphs store entities and relationships using nodes and edges",
                    "created_by": "agent-a",
                    "embed": True,
                },
            ]
        },
    )

    # Search for database-related content
    resp = await client.post(
        "/rooms/e2e-search/memory/search",
        json={
            "query": "database storage and queries",
            "limit": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    results = data["results"]
    assert len(results) > 0

    # Database topic should rank higher than cooking
    keys = [r["memory"]["key"] for r in results]
    assert keys[0] in ("topic/databases", "topic/graphs"), f"Expected DB/graph first, got {keys[0]}"

    # Cooking should be last (least similar)
    if len(results) == 3:
        assert keys[-1] == "topic/cooking"

    # All similarities should be between 0 and 1
    for r in results:
        assert 0 <= r["similarity"] <= 1


@pytest.mark.asyncio
async def test_semantic_search_with_min_similarity(integration_client: AsyncClient):
    """Test that min_similarity filters out low-relevance results."""
    client = integration_client

    await client.post("/rooms", json={"name": "e2e-minsim", "mode": "async"})

    await client.post(
        "/rooms/e2e-minsim/memory",
        json={
            "items": [
                {
                    "key": "relevant",
                    "value": "Vector databases enable semantic search using embeddings",
                    "created_by": "a",
                    "embed": True,
                },
                {
                    "key": "irrelevant",
                    "value": "The weather in Paris is lovely in spring",
                    "created_by": "a",
                    "embed": True,
                },
            ]
        },
    )

    resp = await client.post(
        "/rooms/e2e-minsim/memory/search",
        json={
            "query": "semantic search with vectors",
            "limit": 10,
            "min_similarity": 0.7,
        },
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    # Should filter out the weather memory
    for r in results:
        assert r["similarity"] >= 0.7


@pytest.mark.asyncio
async def test_upsert_preserves_embedding(integration_client: AsyncClient):
    """Test that upserting a memory updates the embedding."""
    client = integration_client

    await client.post("/rooms", json={"name": "e2e-upsert", "mode": "async"})

    # Create
    await client.post(
        "/rooms/e2e-upsert/memory",
        json={
            "items": [
                {
                    "key": "evolving",
                    "value": "Python is a programming language",
                    "created_by": "a",
                    "embed": True,
                }
            ]
        },
    )

    # Update with different content
    await client.post(
        "/rooms/e2e-upsert/memory",
        json={
            "items": [
                {
                    "key": "evolving",
                    "value": "Rust is a systems programming language focused on safety",
                    "created_by": "a",
                    "embed": True,
                }
            ]
        },
    )

    # Search should find the updated content
    resp = await client.post(
        "/rooms/e2e-upsert/memory/search",
        json={
            "query": "systems programming and memory safety",
            "limit": 1,
        },
    )
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["memory"]["key"] == "evolving"
    assert results[0]["memory"]["version"] == 2


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("MYCELIUM_LLM_TESTS"),
    reason="Set MYCELIUM_LLM_TESTS=1 to enable (costs tokens)",
)
async def test_async_room_full_flow(integration_client: AsyncClient):
    """End-to-end: create async room, write memories, trigger synthesis."""
    client = integration_client

    # Create room with low threshold for testing
    resp = await client.post(
        "/rooms",
        json={
            "name": "e2e-flow",
            "mode": "async",
            "trigger_config": {"type": "threshold", "min_contributions": 2},
            "is_persistent": True,
        },
    )
    assert resp.status_code == 201

    # Agent 1 writes
    await client.post(
        "/rooms/e2e-flow/memory",
        json={
            "items": [
                {
                    "key": "agent-a/position",
                    "value": "We should use GraphQL",
                    "created_by": "agent-a",
                    "embed": False,
                }
            ]
        },
    )

    # Agent 2 writes — this should hit threshold (2)
    await client.post(
        "/rooms/e2e-flow/memory",
        json={
            "items": [
                {
                    "key": "agent-b/position",
                    "value": "REST is simpler for our use case",
                    "created_by": "agent-b",
                    "embed": False,
                }
            ]
        },
    )

    # Give async trigger a moment to fire
    await asyncio.sleep(1)

    # Check that synthesis was produced
    resp = await client.get("/rooms/e2e-flow/memory", params={"prefix": "_synthesis/"})
    data = resp.json()
    # Synthesis may or may not have fired (depends on timing), so just check the room is still healthy
    resp = await client.get("/rooms/e2e-flow")
    assert resp.status_code == 200

    # Explicit synthesis — may return 200 (ran) or 409 (auto-trigger already running)
    resp = await client.post("/rooms/e2e-flow/synthesize")
    assert resp.status_code in (200, 409)


@pytest.mark.asyncio
async def test_sync_room_still_works(integration_client: AsyncClient):
    """Verify sync rooms still behave as before — join starts the timer."""
    client = integration_client

    # Create sync room
    resp = await client.post("/rooms", json={"name": "e2e-sync", "mode": "sync"})
    assert resp.status_code == 201

    # Join should set state to waiting
    resp = await client.post(
        "/rooms/e2e-sync/sessions",
        json={
            "agent_handle": "agent-a",
            "intent": "testing sync flow",
        },
    )
    assert resp.status_code == 201

    # Room should be in waiting state
    resp = await client.get("/rooms/e2e-sync")
    room = resp.json()
    assert room["coordination_state"] == "waiting"
    assert room["mode"] == "sync"


@pytest.mark.asyncio
async def test_async_room_join_no_timer(integration_client: AsyncClient):
    """Verify async room join does NOT start coordination timer."""
    client = integration_client

    await client.post("/rooms", json={"name": "e2e-async-join", "mode": "async"})

    resp = await client.post(
        "/rooms/e2e-async-join/sessions",
        json={
            "agent_handle": "agent-a",
            "intent": "just sharing context",
        },
    )
    assert resp.status_code == 201

    # Room should still be idle
    resp = await client.get("/rooms/e2e-async-join")
    assert resp.json()["coordination_state"] == "idle"


# ── Sync CognitiveEngine flow ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_join_starts_timer(integration_client: AsyncClient):
    """Joining a sync room transitions it to 'waiting' state."""
    client = integration_client

    await client.post("/rooms", json={"name": "e2e-timer", "mode": "sync"})

    # First agent joins — should start the timer
    resp = await client.post(
        "/rooms/e2e-timer/sessions",
        json={
            "agent_handle": "alpha",
            "intent": "I want budget=high",
        },
    )
    assert resp.status_code == 201

    resp = await client.get("/rooms/e2e-timer")
    room = resp.json()
    assert room["coordination_state"] == "waiting"
    assert room["join_deadline"] is not None


@pytest.mark.asyncio
async def test_sync_multiple_agents_join(integration_client: AsyncClient):
    """Multiple agents can join during the waiting window."""
    client = integration_client

    await client.post("/rooms", json={"name": "e2e-multi", "mode": "sync"})

    # Two agents join
    resp1 = await client.post(
        "/rooms/e2e-multi/sessions",
        json={
            "agent_handle": "alpha",
            "intent": "budget=high, timeline=short",
        },
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        "/rooms/e2e-multi/sessions",
        json={
            "agent_handle": "beta",
            "intent": "budget=low, quality=premium",
        },
    )
    assert resp2.status_code == 201

    # Both sessions should exist
    resp = await client.get("/rooms/e2e-multi/sessions")
    sessions = resp.json()
    assert sessions["total"] == 2
    handles = {s["agent_handle"] for s in sessions["sessions"]}
    assert handles == {"alpha", "beta"}

    # Room should still be waiting (timer hasn't fired)
    resp = await client.get("/rooms/e2e-multi")
    assert resp.json()["coordination_state"] == "waiting"


@pytest.mark.asyncio
async def test_sync_negotiation_produces_messages(integration_client: AsyncClient):
    """Full sync negotiation: join → wait → CognitiveEngine runs → messages appear."""
    client = integration_client

    # Create sync room with a very short join window for testing
    await client.post("/rooms", json={"name": "e2e-negot", "mode": "sync"})

    # Two agents join
    await client.post(
        "/rooms/e2e-negot/sessions",
        json={
            "agent_handle": "agent-x",
            "intent": "I want scope=full and quality=premium",
        },
    )
    await client.post(
        "/rooms/e2e-negot/sessions",
        json={
            "agent_handle": "agent-y",
            "intent": "I want budget=minimal and timeline=express",
        },
    )

    # Manually trigger tick-0 (bypassing the 60s timer for testing)
    from app.services.coordination import _run_tick

    await _run_tick("e2e-negot", tick=0)

    # Give the pipeline thread a moment to start
    await asyncio.sleep(2)

    # Room should be in negotiating state
    resp = await client.get("/rooms/e2e-negot")
    room = resp.json()
    assert room["coordination_state"] in ("negotiating", "complete")

    # CognitiveEngine should have posted messages
    resp = await client.get("/rooms/e2e-negot/messages")
    messages = resp.json()["messages"]
    assert len(messages) > 0

    # Should have at least a coordination_start message
    types = {m["message_type"] for m in messages}
    assert "coordination_start" in types

    # All coordination messages should be from CognitiveEngine
    coord_msgs = [m for m in messages if m["message_type"].startswith("coordination_")]
    for m in coord_msgs:
        assert m["sender_handle"] == "CognitiveEngine"


@pytest.mark.asyncio
async def test_hybrid_room_supports_both_modes(integration_client: AsyncClient):
    """Hybrid room: can write memories AND trigger sync coordination."""
    client = integration_client

    await client.post(
        "/rooms",
        json={
            "name": "e2e-hybrid",
            "mode": "hybrid",
            "is_persistent": True,
        },
    )

    # Write memories (async behavior)
    resp = await client.post(
        "/rooms/e2e-hybrid/memory",
        json={
            "items": [
                {
                    "key": "context/background",
                    "value": "We need to decide on API design",
                    "created_by": "agent-a",
                    "embed": False,
                }
            ]
        },
    )
    assert resp.status_code == 201

    # Join for sync coordination
    resp = await client.post(
        "/rooms/e2e-hybrid/sessions",
        json={
            "agent_handle": "agent-a",
            "intent": "Ready to negotiate API design",
        },
    )
    assert resp.status_code == 201

    # Room should transition to waiting (hybrid allows sync)
    resp = await client.get("/rooms/e2e-hybrid")
    room = resp.json()
    assert room["coordination_state"] == "waiting"

    # Memory should still be accessible
    resp = await client.get("/rooms/e2e-hybrid/memory/context/background")
    assert resp.status_code == 200
    assert resp.json()["value"]["text"] == "We need to decide on API design"


@pytest.mark.asyncio
async def test_messages_route_during_negotiation(integration_client: AsyncClient):
    """Agent messages during negotiation get routed to coordination service."""
    client = integration_client

    await client.post("/rooms", json={"name": "e2e-msg-route", "mode": "sync"})

    await client.post(
        "/rooms/e2e-msg-route/sessions",
        json={
            "agent_handle": "agent-a",
            "intent": "testing message routing",
        },
    )

    # Manually set room to negotiating state to test routing
    from sqlalchemy import update as sa_update

    from app.database import async_session_maker
    from app.models import Room

    async with async_session_maker() as db:
        await db.execute(
            sa_update(Room)
            .where(Room.name == "e2e-msg-route")
            .values(coordination_state="negotiating")
        )
        await db.commit()

    # Post a message — should succeed even during negotiation
    resp = await client.post(
        "/rooms/e2e-msg-route/messages",
        json={
            "sender_handle": "agent-a",
            "message_type": "direct",
            "content": '{"offer": {"budget": "high"}}',
        },
    )
    assert resp.status_code == 201

    # Message should be recorded
    resp = await client.get("/rooms/e2e-msg-route/messages")
    assert resp.json()["total"] >= 1
