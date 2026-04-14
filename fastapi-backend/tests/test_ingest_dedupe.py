# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for the content-hash TTL dedupe cache."""

import time

from app.services.ingest_dedupe import IngestDedupeCache


def test_hash_stable_under_key_reorder():
    records_a = [{"x": 1, "y": 2, "z": [1, 2, 3]}]
    records_b = [{"z": [1, 2, 3], "y": 2, "x": 1}]
    assert IngestDedupeCache.hash_records(records_a) == IngestDedupeCache.hash_records(
        records_b,
    )


def test_hash_differs_for_different_content():
    assert IngestDedupeCache.hash_records([{"x": 1}]) != IngestDedupeCache.hash_records(
        [{"x": 2}],
    )


def test_lookup_miss_returns_none():
    cache = IngestDedupeCache()
    assert cache.lookup("nonexistent-hash") is None


def test_store_then_lookup_returns_entry():
    cache = IngestDedupeCache()
    h = IngestDedupeCache.hash_records([{"a": 1}])
    cache.store(h, response_id="r-1", message="ok", ttl_seconds=60)
    got = cache.lookup(h)
    assert got is not None
    assert got.response_id == "r-1"
    assert got.message == "ok"


def test_store_with_zero_ttl_is_noop():
    cache = IngestDedupeCache()
    h = IngestDedupeCache.hash_records([{"a": 1}])
    cache.store(h, response_id="r-1", message=None, ttl_seconds=0)
    assert cache.lookup(h) is None
    assert cache.size() == 0


def test_expired_entry_is_lazily_evicted():
    cache = IngestDedupeCache()
    h = IngestDedupeCache.hash_records([{"a": 1}])
    cache.store(h, response_id="r-1", message=None, ttl_seconds=60)
    # Fast-forward: manually expire by rewriting the entry's expires_at.
    with cache._lock:  # noqa: SLF001  (deliberate test-only access)
        cache._entries[h].expires_at = time.monotonic() - 1  # noqa: SLF001
    assert cache.lookup(h) is None
    assert cache.size() == 0


def test_clear_removes_all_entries():
    cache = IngestDedupeCache()
    cache.store("h1", response_id="r1", message=None, ttl_seconds=60)
    cache.store("h2", response_id="r2", message=None, ttl_seconds=60)
    assert cache.size() == 2
    cache.clear()
    assert cache.size() == 0
