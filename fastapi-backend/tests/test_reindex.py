# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the auto-reindex startup scan + watcher glue (reindex.py).

Node-free: the watchdog Observer and the indexer are stubbed, so these pin the
control flow — the startup scan delegates to ``index_all_rooms`` and swallows its
errors, and a watcher file event routes to ``index_single_file``.
"""

from __future__ import annotations

import pytest

from app.services import reindex


@pytest.mark.asyncio
async def test_startup_scan_delegates_to_index_all_rooms(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    async def fake_index_all() -> dict:
        called.append(True)
        return {"rooms": 2, "total_indexed": 3, "total_skipped": 1}

    monkeypatch.setattr("app.services.indexer.index_all_rooms", fake_index_all)
    await reindex.startup_scan()
    assert called == [True]


@pytest.mark.asyncio
async def test_startup_scan_swallows_indexer_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom() -> dict:
        raise RuntimeError("index blew up")

    monkeypatch.setattr("app.services.indexer.index_all_rooms", boom)
    # Startup must not fail because the scan did (it's non-fatal).
    await reindex.startup_scan()


@pytest.mark.asyncio
async def test_reindex_file_delegates_to_index_single_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    async def fake_single(room: str, key: str) -> bool:
        seen.append((room, key))
        return True

    monkeypatch.setattr("app.services.indexer.index_single_file", fake_single)
    await reindex._reindex_file("room-a", "decisions/db")
    assert seen == [("room-a", "decisions/db")]


@pytest.mark.asyncio
async def test_reindex_file_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(room: str, key: str) -> bool:
        raise RuntimeError("nope")

    monkeypatch.setattr("app.services.indexer.index_single_file", boom)
    await reindex._reindex_file("room-a", "k")  # must not raise


def test_start_watcher_is_non_fatal_without_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ``watchdog`` disables the watcher rather than crashing startup."""
    import sys

    # Poisoning the module entries makes the in-function ``from watchdog... import``
    # raise ImportError, exercising the graceful-disable branch even though the
    # package is installed in the dev env.
    monkeypatch.setitem(sys.modules, "watchdog.events", None)
    monkeypatch.setitem(sys.modules, "watchdog.observers", None)
    reindex.start_watcher()  # returns cleanly, observer never created
    assert reindex._observer is None
