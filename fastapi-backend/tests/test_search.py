# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Tests for the local JSONL search index.

Covers brute-force cosine top-k over a seeded index, the /memory/search
endpoint, and rebuild-from-files (reindex).
"""

import pytest
from httpx import AsyncClient

from app.services import search_index


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    """Deterministic stub embeddings so search runs without the ONNX model."""
    monkeypatch.setattr("app.services.embedding._STUB", True)


# ── brute-force cosine over a seeded index (unit) ─────────────────────────────


def _seed(room: str, rows: list[tuple[str, list[float]]]) -> None:
    from app.services.filesystem import get_room_dir

    get_room_dir(room)  # ensure the room dir exists
    search_index.write_index(
        room,
        [
            {"key": key, "room_name": room, "content_text": key, "embedding": emb}
            for key, emb in rows
        ],
    )


def test_search_returns_topk_by_similarity(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    _seed(
        "vec",
        [
            ("east", [1.0, 0.0, 0.0]),
            ("north", [0.0, 1.0, 0.0]),
            ("north-east", [0.9, 0.9, 0.0]),
            ("up", [0.0, 0.0, 1.0]),
        ],
    )

    hits = search_index.search("vec", [1.0, 0.0, 0.0], limit=2)
    assert [key for key, _ in [(r["key"], s) for r, s in hits]] == ["east", "north-east"]
    # similarities are sorted descending and bounded
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_search_min_similarity_filters(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    _seed("vec", [("same", [1.0, 0.0, 0.0]), ("orthogonal", [0.0, 1.0, 0.0])])

    hits = search_index.search("vec", [1.0, 0.0, 0.0], limit=10, min_similarity=0.5)
    assert [r["key"] for r, _ in hits] == ["same"]


def test_records_without_embedding_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    from app.services.filesystem import get_room_dir

    get_room_dir("vec")
    search_index.write_index(
        "vec",
        [
            {"key": "a", "room_name": "vec", "content_text": "a", "embedding": [1.0, 0.0]},
            {"key": "b", "room_name": "vec", "content_text": "b", "embedding": None},
        ],
    )
    hits = search_index.search("vec", [1.0, 0.0], limit=10)
    assert [r["key"] for r, _ in hits] == ["a"]


# ── /memory/search endpoint ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_endpoint_returns_results(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "search-api"})
    await client.post(
        "/api/rooms/search-api/memory",
        json={
            "items": [
                {"key": "a", "value": "graph databases", "created_by": "x", "embed": True},
                {"key": "b", "value": "pasta recipes", "created_by": "x", "embed": True},
            ]
        },
    )

    resp = await client.post(
        "/api/rooms/search-api/memory/search",
        json={"query": "databases", "limit": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == len(data["results"])
    assert data["results"], "expected at least one hit"
    for r in data["results"]:
        assert 0.0 <= r["similarity"] <= 1.0


@pytest.mark.asyncio
async def test_search_skips_unembedded(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "search-noembed"})
    await client.post(
        "/api/rooms/search-noembed/memory",
        json={"items": [{"key": "a", "value": "x", "created_by": "x", "embed": False}]},
    )
    resp = await client.post(
        "/api/rooms/search-noembed/memory/search", json={"query": "x", "limit": 5}
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


# ── reindex rebuilds the JSONL from the markdown files ────────────────────────


@pytest.mark.asyncio
async def test_reindex_rebuilds_index_from_files(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "rebuild"})
    await client.post(
        "/api/rooms/rebuild/memory",
        json={
            "items": [
                {"key": "decisions/db", "value": "postgres", "created_by": "a", "embed": True},
                {"key": "decisions/lang", "value": "python", "created_by": "a", "embed": True},
            ]
        },
    )

    # Wipe the derived index; the markdown files remain canonical.
    search_index.index_path("rebuild").unlink()
    assert search_index.load_index("rebuild") == []

    resp = await client.post("/api/rooms/rebuild/reindex")
    assert resp.status_code == 200
    assert resp.json()["indexed"] == 2

    keys = sorted(r["key"] for r in search_index.load_index("rebuild"))
    assert keys == ["decisions/db", "decisions/lang"]
