# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Integration tests — require a running Postgres/AgensGraph with pgvector.

These tests hit the real database to verify vector embedding + semantic search
end-to-end.

Skip automatically if DATABASE_URL is not set or DB is unreachable.

Run with:
    DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5555/mycelium \
        uv run pytest tests/test_integration.py -x -v
"""

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

    import app.database as _db_module
    from app.database import get_async_session
    from app.main import app
    from app.models import Base

    engine = create_async_engine(INTEGRATION_DB_URL)

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    # Override the module-level session_maker so HTTP-layer and background DB
    # ops share one engine and avoid concurrent-operation errors on pooled
    # connections.
    _orig_session_maker = _db_module.async_session_maker
    _db_module.async_session_maker = session_maker

    async def _override_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

    _db_module.async_session_maker = _orig_session_maker

    # Clean up tables after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_memory_create_with_embedding(integration_client: AsyncClient):
    """Test that memories are created with vector embeddings."""
    client = integration_client

    # Create async room
    resp = await client.post("/api/rooms", json={"name": "e2e-embed"})
    assert resp.status_code == 201

    # Create memory with embedding (embed=True is default)
    resp = await client.post(
        "/api/rooms/e2e-embed/memory",
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

    await client.post("/api/rooms", json={"name": "e2e-search"})

    # Write several memories with different topics
    await client.post(
        "/api/rooms/e2e-search/memory",
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
        "/api/rooms/e2e-search/memory/search",
        json={
            "query": "database storage and queries",
            "limit": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    results = data["results"]
    assert len(results) > 0

    # Ordering assertions require real embeddings; skip when stub is active.
    if not os.getenv("MYCELIUM_STUB_EMBEDDINGS"):
        keys = [r["memory"]["key"] for r in results]
        assert keys[0] in ("topic/databases", "topic/graphs"), (
            f"Expected DB/graph first, got {keys[0]}"
        )
        if len(results) == 3:
            assert keys[-1] == "topic/cooking"

    # All similarities should be between 0 and 1
    for r in results:
        assert 0 <= r["similarity"] <= 1


@pytest.mark.asyncio
async def test_semantic_search_with_min_similarity(integration_client: AsyncClient):
    """Test that min_similarity filters out low-relevance results."""
    client = integration_client

    await client.post("/api/rooms", json={"name": "e2e-minsim"})

    await client.post(
        "/api/rooms/e2e-minsim/memory",
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
        "/api/rooms/e2e-minsim/memory/search",
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

    await client.post("/api/rooms", json={"name": "e2e-upsert"})

    # Create
    await client.post(
        "/api/rooms/e2e-upsert/memory",
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
        "/api/rooms/e2e-upsert/memory",
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
        "/api/rooms/e2e-upsert/memory/search",
        json={
            "query": "systems programming and memory safety",
            "limit": 1,
        },
    )
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["memory"]["key"] == "evolving"
    assert results[0]["memory"]["version"] == 2
