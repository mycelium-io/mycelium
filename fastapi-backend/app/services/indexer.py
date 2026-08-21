# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Filesystem → JSONL search indexer.

Scans ``.mycelium/rooms/{room}/`` directories, reads markdown files, and upserts
``{embedding, metadata}`` records into each room's JSONL search index
(``services.search_index``). The markdown files are canonical; the index is
derived and fully rebuildable from them.

Incremental: compares file mtime against the indexed ``updated_at`` and skips
unchanged files (unless ``force``).
"""

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from app.services import links, search_index
from app.services.embedding import embed_text
from app.services.filesystem import (
    get_data_dir,
    list_memory_files,
    parse_memory,
    parse_timestamp,
)

logger = logging.getLogger(__name__)


def _file_mtime(base_dir: Path, key: str) -> datetime:
    """Get mtime of a memory file as a UTC datetime."""
    filename = key + ".md" if not key.endswith(".md") else key
    path = base_dir / filename
    return datetime.fromtimestamp(os.path.getmtime(path), tz=UTC)


def _iso(value: str | datetime | None, default: datetime) -> str:
    """Normalize a frontmatter timestamp to an ISO-8601 string."""
    return (parse_timestamp(value) or default).isoformat()


def _build_record(room_name: str, key: str, content: str, meta: dict) -> dict:
    """Build a JSONL index record (with embedding) for one memory."""
    content_text = content or key
    embedding = embed_text(content_text)
    now = datetime.now(UTC)
    created_by = meta.get("created_by", "filesystem")
    return {
        "key": key,
        "room_name": room_name,
        "content_text": content_text,
        "embedding": embedding,
        "value": meta.get("value"),
        "created_by": created_by,
        "updated_by": meta.get("updated_by", created_by),
        "version": meta.get("version", 1),
        "tags": meta.get("tags"),
        "expandable": links.is_expandable(meta),
        "created_at": _iso(meta.get("created_at"), now),
        "updated_at": _iso(meta.get("updated_at"), now),
        "file_path": f"rooms/{room_name}/{key}.md",
    }


async def index_room(room_name: str, *, force: bool = False) -> dict:
    """Scan a room's directory and rebuild its JSONL search index.

    When ``force`` is False, skips files unchanged since last index and prunes
    records whose files no longer exist. Returns stats.
    """
    t0 = time.monotonic()
    data_dir = get_data_dir()
    room_dir = data_dir / "rooms" / room_name
    stats = {"indexed": 0, "skipped": 0, "pruned": 0, "errors": 0}
    if ":session:" in room_name or not room_dir.exists():
        return stats

    existing = {r["key"]: r for r in search_index.load_index(room_name)}
    entries = list_memory_files(room_dir, limit=10000)
    file_keys = set()
    records: list[dict] = []

    for key, meta, content in entries:
        file_keys.add(key)
        try:
            prior = existing.get(key)
            if not force and prior is not None:
                mtime = _file_mtime(room_dir, key)
                indexed_at = parse_timestamp(prior.get("updated_at"))
                if indexed_at and indexed_at >= mtime:
                    records.append(prior)
                    stats["skipped"] += 1
                    continue
            record = await asyncio.to_thread(_build_record, room_name, key, content, meta)
            records.append(record)
            stats["indexed"] += 1
        except Exception:
            logger.warning("Failed to index %s/%s", room_name, key, exc_info=True)
            stats["errors"] += 1
            if key in existing:
                records.append(existing[key])

    # Anything in the old index whose file vanished is pruned by omission.
    stats["pruned"] = sum(1 for k in existing if k not in file_keys)
    search_index.write_index(room_name, records)

    # The link index is cheap to rebuild wholesale (a parse, no embeddings), and
    # a full rebuild is the only way stale edges from a since-deleted file go away.
    links.rebuild(room_name)

    from app.services.metrics import record_index_run

    record_index_run(
        target="room",
        indexed=stats["indexed"],
        skipped=stats["skipped"],
        pruned=stats["pruned"],
        errors=stats["errors"],
        duration_ms=(time.monotonic() - t0) * 1000,
    )
    return stats


async def index_all_rooms(*, force: bool = False) -> dict:
    """Scan and index every room."""
    data_dir = get_data_dir()
    rooms_dir = data_dir / "rooms"
    if not rooms_dir.exists():
        return {"rooms": 0, "total_indexed": 0, "total_skipped": 0}

    total_indexed = 0
    total_skipped = 0
    rooms_count = 0
    for room_dir in sorted(rooms_dir.iterdir()):
        if room_dir.is_dir() and ":session:" not in room_dir.name:
            stats = await index_room(room_dir.name, force=force)
            total_indexed += stats["indexed"]
            total_skipped += stats["skipped"]
            rooms_count += 1

    return {"rooms": rooms_count, "total_indexed": total_indexed, "total_skipped": total_skipped}


async def index_single_file(room_name: str, key: str) -> bool:
    """Index (or prune) a single memory file. Used by the file watcher."""
    t0 = time.monotonic()
    from app.services.metrics import record_index_run

    data_dir = get_data_dir()
    room_dir = data_dir / "rooms" / room_name
    file_path = room_dir / (key + ".md" if not key.endswith(".md") else key)

    if not file_path.exists():
        pruned = search_index.remove(room_name, key)
        links.remove(room_name, key)
        record_index_run(
            target="watcher",
            pruned=1 if pruned else 0,
            duration_ms=(time.monotonic() - t0) * 1000,
        )
        return pruned

    try:
        meta, content = parse_memory(file_path.read_text(encoding="utf-8"))
        record = await asyncio.to_thread(_build_record, room_name, key, content, meta)
        search_index.upsert(room_name, record)
        links.upsert(room_name, key, meta, content)
        record_index_run(target="watcher", indexed=1, duration_ms=(time.monotonic() - t0) * 1000)
        return True
    except Exception:
        logger.warning("Failed to index single file %s/%s", room_name, key, exc_info=True)
        record_index_run(target="watcher", errors=1, duration_ms=(time.monotonic() - t0) * 1000)
        return False
