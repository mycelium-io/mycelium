# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Local JSON-Lines search index.

One JSONL file per room lives beside the room's markdown at
``.mycelium/rooms/{room}/.search-index.jsonl``; each line is one record::

    {"key", "room_name", "content_text", "embedding": [384 floats],
     "created_by", "updated_by", "version", "tags",
     "created_at", "updated_at", "file_path"}

Search is brute-force cosine in-process — fine at personal scale (hundreds to
low-thousands of memories per room). A real ANN index is a later problem.

The markdown files are canonical; this index is derived and can always be
rebuilt from them via ``services.reindex`` / ``services.indexer``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from pathlib import Path

from app.services.filesystem import get_data_dir

logger = logging.getLogger(__name__)

INDEX_FILENAME = ".search-index.jsonl"

# Stable UUIDs derived from (room, key) so a memory keeps the same id across
# reads without a database to mint one. uuid5 is deterministic and collision-free
# for distinct (room, key) pairs.
_ID_NAMESPACE = uuid.UUID("6f8a5b3e-9c1d-4e2a-8b7c-1a2b3c4d5e6f")


def stable_memory_id(room_name: str, key: str) -> uuid.UUID:
    """Return the deterministic UUID for a memory identified by (room, key)."""
    return uuid.uuid5(_ID_NAMESPACE, f"{room_name}/{key}")


def index_path(room_name: str) -> Path:
    """Path to a room's JSONL search index (not created here)."""
    return get_data_dir() / "rooms" / room_name / INDEX_FILENAME


def load_index(room_name: str) -> list[dict]:
    """Load all index records for a room. Returns [] if the index is absent."""
    path = index_path(room_name)
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed index line in %s", path)
    return records


def write_index(room_name: str, records: list[dict]) -> None:
    """Atomically rewrite a room's JSONL index."""
    path = index_path(room_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, default=str))
            fh.write("\n")
    os.replace(tmp, path)


def upsert(room_name: str, record: dict) -> None:
    """Insert or replace the record for ``record['key']`` in the room index."""
    key = record["key"]
    records = load_index(room_name)
    records = [r for r in records if r.get("key") != key]
    records.append(record)
    write_index(room_name, records)


def remove(room_name: str, key: str) -> bool:
    """Drop the record for ``key``. Returns True if a record was removed."""
    records = load_index(room_name)
    kept = [r for r in records if r.get("key") != key]
    if len(kept) == len(records):
        return False
    write_index(room_name, kept)
    return True


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors. 0.0 on a zero vector."""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def search(
    room_name: str,
    query_embedding: list[float],
    *,
    limit: int,
    min_similarity: float = 0.0,
) -> list[tuple[dict, float]]:
    """Brute-force cosine search over a room's index.

    Returns up to ``limit`` ``(record, similarity)`` pairs sorted by descending
    similarity, filtered to those at/above ``min_similarity``. Records without a
    stored embedding are skipped.
    """
    scored: list[tuple[dict, float]] = []
    for rec in load_index(room_name):
        embedding = rec.get("embedding")
        if not embedding:
            continue
        sim = cosine_similarity(query_embedding, embedding)
        if sim < min_similarity:
            continue
        scored.append((rec, sim))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]
