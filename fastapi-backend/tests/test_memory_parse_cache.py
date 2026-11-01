# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The parsed-file cache under memory reads: reused while a file is unchanged,
parsed afresh the moment it changes, and never shared between callers."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from app.services import filesystem as fs

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _empty_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fs._parse_cache.clear()
    # Files here are written a moment before they're read; the window that
    # keeps a just-changed file out of the cache has its own tests below.
    monkeypatch.setattr(fs, "RACY_WINDOW_NS", 0)


def _read(base: Path, key: str) -> tuple[dict, str]:
    found = fs.read_memory_file(base, key)
    assert found is not None
    return found


def _count_parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real = fs.parse_memory

    def counting(text: str) -> tuple[dict, str]:
        seen.append(text)
        return real(text)

    monkeypatch.setattr(fs, "parse_memory", counting)
    return seen


def test_an_unchanged_file_is_parsed_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fs.write_memory_file(tmp_path, "work/a", "body", created_by="julia")
    parses = _count_parses(monkeypatch)
    for _ in range(3):
        assert [k for k, _m, _c in fs.list_memory_files(tmp_path)] == ["work/a"]
    assert fs.read_memory_file(tmp_path, "work/a") is not None
    assert len(parses) == 1


def test_a_changed_file_is_parsed_again(tmp_path: Path) -> None:
    fs.write_memory_file(tmp_path, "work/a", "first", created_by="julia")
    assert _read(tmp_path, "work/a")[1] == "first"
    path = fs.write_memory_file(tmp_path, "work/a", "second, longer", created_by="sam")
    meta, content = _read(tmp_path, "work/a")
    assert content == "second, longer"
    assert meta["created_by"] == "sam"
    # Same size, edited on disk: re-read once the stamp moves.
    path.write_text(path.read_text().replace("second", "SECOND"))
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert _read(tmp_path, "work/a")[1] == "SECOND, longer"


def test_callers_get_their_own_copy(tmp_path: Path) -> None:
    fs.write_memory_file(tmp_path, "work/a", "body", created_by="julia", tags=["x"])
    meta, _ = _read(tmp_path, "work/a")
    meta["created_by"] = "mallory"
    meta["tags"].append("y")
    again, _ = _read(tmp_path, "work/a")
    assert again["created_by"] == "julia"
    assert again["tags"] == ["x"]


def test_the_cache_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "PARSE_CACHE_MAX", 3)
    for i in range(5):
        fs.write_memory_file(tmp_path, f"work/{i}", "body", created_by="julia")
    fs.list_memory_files(tmp_path)
    assert len(fs._parse_cache) == 3


def test_a_file_changed_a_moment_ago_is_not_cached_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fs, "RACY_WINDOW_NS", 2_000_000_000)
    path = fs.write_memory_file(tmp_path, "work/a", "fresh", created_by="julia")
    assert _read(tmp_path, "work/a")[1] == "fresh"
    assert str(path) not in fs._parse_cache
    # Once it has settled, it's cached.
    old = path.stat().st_mtime_ns - 10_000_000_000
    os.utime(path, ns=(old, old))
    _read(tmp_path, "work/a")
    assert str(path) in fs._parse_cache


def test_a_same_size_rewrite_in_the_same_tick_is_still_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The case the window exists for: a coarse-clock filesystem gives two
    # same-size writes the same stamp. Simulated by pinning the mtime back.
    monkeypatch.setattr(fs, "RACY_WINDOW_NS", 2_000_000_000)
    path = fs.write_memory_file(tmp_path, "work/a", "aaaa", created_by="julia")
    stamp = path.stat().st_mtime_ns
    assert _read(tmp_path, "work/a")[1] == "aaaa"
    path.write_text(path.read_text().replace("aaaa", "bbbb"))
    os.utime(path, ns=(stamp, stamp))
    assert _read(tmp_path, "work/a")[1] == "bbbb"
