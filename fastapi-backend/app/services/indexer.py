# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Filesystem → pgvector indexer.

Scans .mycelium/rooms/{room}/ and .mycelium/notebooks/{handle}/ directories,
reads markdown files, and upserts embeddings into the memories table.

Incremental: compares file mtime against DB updated_at and skips unchanged files.
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Memory
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


async def index_room(room_name: str, db: AsyncSession, *, force: bool = False) -> dict:
    """Scan a room's directory and upsert embeddings into the search index.

    When force=False (default), skips files that haven't changed since last index.
    Also prunes DB records whose files no longer exist on disk.

    Returns stats: {"indexed": N, "skipped": N, "pruned": N, "errors": N}
    """
    data_dir = get_data_dir()
    room_dir = data_dir / "rooms" / room_name
    if not room_dir.exists():
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
                existing = await _find_existing(db, room_name, key, "namespace", None)
                if existing and existing.updated_at and existing.updated_at >= mtime:
                    stats["skipped"] += 1
                    continue

            await _index_single_memory(
                db=db,
                room_name=room_name,
                key=key,
                content=content,
                meta=meta,
                scope="namespace",
                owner_handle=None,
                file_path=f"rooms/{room_name}/{key}.md",
            )
            stats["indexed"] += 1
        except Exception:
            logger.warning("Failed to index %s/%s", room_name, key, exc_info=True)
            stats["errors"] += 1

    # Prune DB records whose files no longer exist
    result = await db.execute(
        select(Memory).where(
            Memory.room_name == room_name,
            Memory.scope == "namespace",
            Memory.owner_handle.is_(None),
        )
    )
    for mem in result.scalars().all():
        if mem.key not in file_keys:
            await db.delete(mem)
            stats["pruned"] += 1

    await db.commit()
    return stats


async def index_notebook(handle: str, db: AsyncSession, *, force: bool = False) -> dict:
    """Scan an agent's notebook directory and upsert embeddings."""
    data_dir = get_data_dir()
    notebook_dir = data_dir / "notebooks" / handle
    if not notebook_dir.exists():
        return {"indexed": 0, "skipped": 0, "pruned": 0, "errors": 0}

    entries = list_memory_files(notebook_dir, limit=10000)
    stats = {"indexed": 0, "skipped": 0, "pruned": 0, "errors": 0}

    for key, meta, content in entries:
        try:
            if not force:
                mtime = _file_mtime(notebook_dir, key)
                existing = await _find_existing(db, "_notebooks", key, "notebook", handle)
                if existing and existing.updated_at and existing.updated_at >= mtime:
                    stats["skipped"] += 1
                    continue

            await _index_single_memory(
                db=db,
                room_name="_notebooks",
                key=key,
                content=content,
                meta=meta,
                scope="notebook",
                owner_handle=handle,
                file_path=f"notebooks/{handle}/{key}.md",
            )
            stats["indexed"] += 1
        except Exception:
            logger.warning("Failed to index notebook %s/%s", handle, key, exc_info=True)
            stats["errors"] += 1

    await db.commit()
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
    data_dir = get_data_dir()
    room_dir = data_dir / "rooms" / room_name
    file_path = room_dir / (key + ".md" if not key.endswith(".md") else key)

    if not file_path.exists():
        # File was deleted — remove from DB
        await db.execute(
            delete(Memory).where(
                Memory.room_name == room_name,
                Memory.key == key,
                Memory.scope == "namespace",
            )
        )
        await db.commit()
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
            scope="namespace",
            owner_handle=None,
            file_path=f"rooms/{room_name}/{key}.md",
        )
        await db.commit()
        return True
    except Exception:
        logger.warning("Failed to index single file %s/%s", room_name, key, exc_info=True)
        return False


async def _find_existing(
    db: AsyncSession, room_name: str, key: str, scope: str, owner_handle: str | None
) -> Memory | None:
    """Find an existing memory record."""
    query = select(Memory).where(
        Memory.room_name == room_name,
        Memory.key == key,
        Memory.scope == scope,
    )
    if scope == "notebook":
        query = query.where(Memory.owner_handle == owner_handle)
    else:
        query = query.where(Memory.owner_handle.is_(None))
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _index_single_memory(
    *,
    db: AsyncSession,
    room_name: str,
    key: str,
    content: str,
    meta: dict,
    scope: str,
    owner_handle: str | None,
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

    existing = await _find_existing(db, room_name, key, scope, owner_handle)

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
            scope=scope,
            owner_handle=owner_handle,
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
