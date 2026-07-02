# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Filesystem → pgvector indexer.

Scans .mycelium/rooms/{room}/ directories, reads markdown files, and upserts
embeddings into the memories table.

Incremental: compares file mtime against DB updated_at and skips unchanged files.
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Memory, Room
from app.services.embedding import embed_text
from app.services.filesystem import (
    get_data_dir,
    list_memory_files,
)

logger = logging.getLogger(__name__)


def _file_mtime(base_dir: Path, key: str) -> datetime:
    """Get mtime of a memory file as a UTC datetime."""
    filename = key + ".md" if not key.endswith(".md") else key
    path = base_dir / filename
    return datetime.fromtimestamp(os.path.getmtime(path), tz=UTC)


async def _ensure_room(db: AsyncSession, room_name: str) -> bool:
    """Ensure a Room row exists for room_name. Returns False if the directory
    should be skipped entirely (coordination session sub-room).

    After a volume wipe the filesystem survives but the DB is empty; this
    upserts the Room row so the FK on memories.room_name → rooms.name is
    satisfied.

    Session sub-rooms ({room}:session:{short_id}) are excluded by string check
    rather than a DB lookup. A DB lookup can't reliably distinguish them on a
    fresh DB (CoordinationSession table is also empty after a volume wipe), and
    ':session:' is an internal convention enforced by _spawn_coordination_session
    — it is not reachable via normal `mycelium room create` usage.
    """
    if ":session:" in room_name:
        return False
    result = await db.execute(select(Room).where(Room.name == room_name))
    if result.scalar_one_or_none() is not None:
        return True
    db.add(Room(name=room_name, is_public=True, namespace=room_name))
    try:
        await db.flush()
    except Exception:
        await db.rollback()
    return True


async def index_room(room_name: str, db: AsyncSession, *, force: bool = False) -> dict:
    """Scan a room's directory and upsert embeddings into the search index.

    When force=False (default), skips files that haven't changed since last index.
    Also prunes DB records whose files no longer exist on disk.

    Returns stats: {"indexed": N, "skipped": N, "pruned": N, "errors": N}
    """
    import time

    t0 = time.monotonic()
    data_dir = get_data_dir()
    room_dir = data_dir / "rooms" / room_name
    if not room_dir.exists():
        return {"indexed": 0, "skipped": 0, "pruned": 0, "errors": 0}

    # Ensure the room has a DB row before inserting Memory rows.
    # Returns False for session sub-rooms, which are skipped entirely.
    if not await _ensure_room(db, room_name):
        return {"indexed": 0, "skipped": 0, "pruned": 0, "errors": 0}

    entries = list_memory_files(room_dir, limit=10000)
    file_keys = set()
    stats = {"indexed": 0, "skipped": 0, "pruned": 0, "errors": 0}

    for key, meta, content in entries:
        file_keys.add(key)
        try:
            # Check if file has changed since last index
            if not force:
                mtime = _file_mtime(room_dir, key)
                existing = await _find_existing(db, room_name, key)
                if existing and existing.updated_at and existing.updated_at >= mtime:
                    stats["skipped"] += 1
                    continue

            await _index_single_memory(
                db=db,
                room_name=room_name,
                key=key,
                content=content,
                meta=meta,
                file_path=f"rooms/{room_name}/{key}.md",
            )
            stats["indexed"] += 1
        except Exception:
            logger.warning("Failed to index %s/%s", room_name, key, exc_info=True)
            stats["errors"] += 1

    # Prune DB records whose files no longer exist
    result = await db.execute(select(Memory).where(Memory.room_name == room_name))
    for mem in result.scalars().all():
        if mem.key not in file_keys:
            await db.delete(mem)
            stats["pruned"] += 1

    await db.commit()

    from app.services.metrics import record_index_run

    elapsed_ms = (time.monotonic() - t0) * 1000
    record_index_run(
        target="room",
        indexed=stats["indexed"],
        skipped=stats["skipped"],
        pruned=stats["pruned"],
        errors=stats["errors"],
        duration_ms=elapsed_ms,
    )

    return stats


async def index_all_rooms(db: AsyncSession, *, force: bool = False) -> dict:
    """Scan all rooms and index them."""
    data_dir = get_data_dir()
    rooms_dir = data_dir / "rooms"
    if not rooms_dir.exists():
        return {"rooms": 0, "total_indexed": 0, "total_skipped": 0}

    total_indexed = 0
    total_skipped = 0
    rooms_count = 0
    for room_dir in sorted(rooms_dir.iterdir()):
        if room_dir.is_dir():
            stats = await index_room(room_dir.name, db, force=force)
            total_indexed += stats["indexed"]
            total_skipped += stats["skipped"]
            rooms_count += 1

    return {"rooms": rooms_count, "total_indexed": total_indexed, "total_skipped": total_skipped}


async def index_single_file(room_name: str, key: str, db: AsyncSession) -> bool:
    """Index a single memory file. Used by the file watcher.

    Returns True if indexed, False if skipped/error.
    """
    import time

    from app.services.metrics import record_index_run

    t0 = time.monotonic()
    data_dir = get_data_dir()
    room_dir = data_dir / "rooms" / room_name
    file_path = room_dir / (key + ".md" if not key.endswith(".md") else key)

    if not file_path.exists():
        # File was deleted — remove from DB
        await db.execute(
            delete(Memory).where(
                Memory.room_name == room_name,
                Memory.key == key,
            )
        )
        await db.commit()
        record_index_run(target="watcher", pruned=1, duration_ms=(time.monotonic() - t0) * 1000)
        return True

    try:
        from app.services.filesystem import parse_memory

        text = file_path.read_text(encoding="utf-8")
        meta, content = parse_memory(text)

        await _index_single_memory(
            db=db,
            room_name=room_name,
            key=key,
            content=content,
            meta=meta,
            file_path=f"rooms/{room_name}/{key}.md",
        )
        await db.commit()
        record_index_run(target="watcher", indexed=1, duration_ms=(time.monotonic() - t0) * 1000)
        return True
    except Exception:
        logger.warning("Failed to index single file %s/%s", room_name, key, exc_info=True)
        record_index_run(target="watcher", errors=1, duration_ms=(time.monotonic() - t0) * 1000)
        return False


async def _find_existing(db: AsyncSession, room_name: str, key: str) -> Memory | None:
    """Find an existing memory record."""
    result = await db.execute(
        select(Memory).where(Memory.room_name == room_name, Memory.key == key)
    )
    return result.scalar_one_or_none()


async def _index_single_memory(
    *,
    db: AsyncSession,
    room_name: str,
    key: str,
    content: str,
    meta: dict,
    file_path: str,
) -> None:
    """Upsert a single memory into the pgvector search index."""
    import asyncio

    content_text = content or key
    embedding = await asyncio.to_thread(embed_text, content_text)
    value = {"text": content} if content else {}

    now = datetime.now(UTC)
    created_by = meta.get("created_by", "filesystem")
    updated_by = meta.get("updated_by", created_by)
    version = meta.get("version", 1)
    tags = meta.get("tags")

    created_at = _parse_datetime(meta.get("created_at")) or now
    updated_at = _parse_datetime(meta.get("updated_at")) or now

    existing = await _find_existing(db, room_name, key)

    if existing:
        existing.value = value
        existing.content_text = content_text
        existing.embedding = embedding
        existing.updated_by = updated_by
        existing.version = version
        existing.tags = tags
        existing.updated_at = updated_at
        existing.file_path = file_path
        await db.flush()
    else:
        mem = Memory(
            room_name=room_name,
            key=key,
            value=value,
            content_text=content_text,
            embedding=embedding,
            created_by=created_by,
            updated_by=updated_by,
            version=version,
            tags=tags,
            file_path=file_path,
        )
        mem.created_at = created_at
        mem.updated_at = updated_at
        db.add(mem)
        await db.flush()


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse a datetime from a YAML frontmatter value."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
