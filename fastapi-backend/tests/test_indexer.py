# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the filesystem→JSONL indexer (app/services/indexer.py).

Node-free and model-free: ``embed_text`` is stubbed with a deterministic vector
so these run without downloading the ONNX embedding model, and the markdown lives
under the temp ``MYCELIUM_DATA_DIR`` ``conftest`` provides. They pin the pieces
the API tests only hit end-to-end: the incremental skip, the prune-by-omission,
and the single-file index/prune the watcher drives.
"""

from __future__ import annotations

import pytest

from app.services import indexer, search_index
from app.services.filesystem import get_room_dir, write_memory_file


@pytest.fixture(autouse=True)
def _stub_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the ONNX embedder with a cheap deterministic vector."""
    monkeypatch.setattr(indexer, "embed_text", lambda text: [float(len(text)), 1.0, 0.0])


def _write(room: str, key: str, value: str) -> None:
    write_memory_file(get_room_dir(room), key, value, created_by="tester")


@pytest.mark.asyncio
async def test_index_room_builds_records_for_every_file() -> None:
    _write("room-a", "decisions/db", "postgres")
    _write("room-a", "decisions/lang", "python")

    stats = await indexer.index_room("room-a")

    assert stats["indexed"] == 2
    keys = sorted(r["key"] for r in search_index.load_index("room-a"))
    assert keys == ["decisions/db", "decisions/lang"]


@pytest.mark.asyncio
async def test_index_room_skips_unchanged_on_second_pass() -> None:
    import os

    _write("room-a", "decisions/db", "postgres")
    first = await indexer.index_room("room-a")
    assert first["indexed"] == 1

    # Backdate the file so the incremental indexer skips it.
    path = get_room_dir("room-a") / "decisions" / "db.md"
    past = path.stat().st_mtime - 3600
    os.utime(path, (past, past))

    second = await indexer.index_room("room-a")
    assert second["indexed"] == 0 and second["skipped"] == 1


@pytest.mark.asyncio
async def test_index_room_force_reindexes_unchanged() -> None:
    _write("room-a", "decisions/db", "postgres")
    await indexer.index_room("room-a")

    forced = await indexer.index_room("room-a", force=True)
    assert forced["indexed"] == 1 and forced["skipped"] == 0


@pytest.mark.asyncio
async def test_index_room_prunes_vanished_files() -> None:
    _write("room-a", "decisions/db", "postgres")
    _write("room-a", "decisions/lang", "python")
    await indexer.index_room("room-a")

    # Delete one markdown file; its index record should be pruned by omission.
    (get_room_dir("room-a") / "decisions" / "lang.md").unlink()
    stats = await indexer.index_room("room-a")

    assert stats["pruned"] == 1
    assert [r["key"] for r in search_index.load_index("room-a")] == ["decisions/db"]


@pytest.mark.asyncio
async def test_index_room_ignores_session_scoped_names() -> None:
    stats = await indexer.index_room("room-a:session:abcd1234")
    assert stats == {"indexed": 0, "skipped": 0, "pruned": 0, "errors": 0}


@pytest.mark.asyncio
async def test_index_all_rooms_counts_rooms_and_skips_sessions() -> None:
    _write("room-a", "k", "va")
    _write("room-b", "k", "vb")
    # A session-scoped directory must be excluded from the room walk.
    _write("room-a:session:zzzz", "k", "vs")

    result = await indexer.index_all_rooms()
    assert result["rooms"] == 2
    assert result["total_indexed"] == 2


@pytest.mark.asyncio
async def test_index_single_file_indexes_then_prunes() -> None:
    _write("room-a", "decisions/db", "postgres")

    assert await indexer.index_single_file("room-a", "decisions/db") is True
    assert [r["key"] for r in search_index.load_index("room-a")] == ["decisions/db"]

    (get_room_dir("room-a") / "decisions" / "db.md").unlink()
    # File gone → the single-file path prunes the stale record (True = it acted).
    assert await indexer.index_single_file("room-a", "decisions/db") is True
    assert search_index.load_index("room-a") == []
    # Nothing left to prune → a repeat is a no-op (False).
    assert await indexer.index_single_file("room-a", "decisions/db") is False


@pytest.mark.asyncio
async def test_index_record_carries_unmanaged_frontmatter() -> None:
    """A rebuilt index keeps user frontmatter, so search answers like a get does."""
    write_memory_file(
        get_room_dir("room-meta"),
        "work/x",
        "blocked",
        created_by="tester",
        extra_meta={"status": "open"},
    )

    await indexer.index_room("room-meta")

    record = search_index.load_index("room-meta")[0]
    assert record["meta"] == {"status": "open"}
