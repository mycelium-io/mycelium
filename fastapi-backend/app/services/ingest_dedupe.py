# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Content-hash TTL dedupe cache for CFN shared-memories forwards.

In-memory, process-wide, threadsafe. Keyed on ``sha256(json.dumps(records,
sort_keys=True))`` so callers that send the same payload twice within the
TTL get the previously-cached CFN ``response_id`` without re-hitting CFN.

This is a defense-in-depth mechanism against the hook-side race in
mycelium-knowledge-extract and any future regression that causes duplicate
POSTs. The audit_events table remains the durable record; this cache is a
cost-control aid.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class DedupeEntry:
    response_id: str
    message: str | None
    expires_at: float


class IngestDedupeCache:
    """Threadsafe hash → (response_id, expiry) map with lazy TTL eviction."""

    def __init__(self) -> None:
        self._entries: dict[str, DedupeEntry] = {}
        self._lock = threading.Lock()

    @staticmethod
    def hash_records(records: list[dict[str, Any]]) -> str:
        """Stable SHA256 hash of the records payload.

        Uses ``sort_keys=True`` so two dicts with the same content produce
        the same hash regardless of key order.
        """
        blob = json.dumps(records, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def lookup(self, content_hash: str) -> DedupeEntry | None:
        """Return a non-expired entry, or ``None`` if missing/expired.

        Lazily evicts the entry if expired.
        """
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(content_hash)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(content_hash, None)
                return None
            return entry

    def store(
        self,
        content_hash: str,
        *,
        response_id: str,
        message: str | None,
        ttl_seconds: int,
    ) -> None:
        """Cache a successful CFN response under ``content_hash``."""
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._entries[content_hash] = DedupeEntry(
                response_id=response_id,
                message=message,
                expires_at=time.monotonic() + ttl_seconds,
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._entries)


_cache: IngestDedupeCache | None = None


def get_cache() -> IngestDedupeCache:
    """Return the process-wide ingest dedupe cache, creating it lazily."""
    global _cache
    if _cache is None:
        _cache = IngestDedupeCache()
    return _cache
