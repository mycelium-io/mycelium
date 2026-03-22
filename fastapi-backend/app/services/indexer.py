"""
Filesystem → pgvector indexer.

Scans .mycelium/rooms/{room}/ and .mycelium/notebooks/{handle}/ directories,
reads markdown files, and upserts embeddings into the memories table.

Leverages the existing embedding service (sentence-transformers/all-MiniLM-L6-v2)
and the evidence_gathering chunker for long documents.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Memory
from app.services.embedding import embed_text
from app.services.filesystem import (
    get_data_dir,
    list_memory_files,
)

logger = logging.getLogger(__name__)


async def index_room(room_name: str, db: AsyncSession) -> dict:
    """Scan a room's directory and upsert embeddings into the search index.

    Returns stats: {"indexed": N, "skipped": N, "errors": N}
    """
    data_dir = get_data_dir()
    room_dir = data_dir / "rooms" / room_name
    if not room_dir.exists():
        return {"indexed": 0, "skipped": 0, "errors": 0, "message": "Room directory not found"}

    entries = list_memory_files(room_dir, limit=10000)
    stats = {"indexed": 0, "skipped": 0, "errors": 0}

    for key, meta, content in entries:
        try:
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

    await db.commit()
    return stats


async def index_notebook(handle: str, db: AsyncSession) -> dict:
    """Scan an agent's notebook directory and upsert embeddings."""
    data_dir = get_data_dir()
    notebook_dir = data_dir / "notebooks" / handle
    if not notebook_dir.exists():
        return {"indexed": 0, "skipped": 0, "errors": 0, "message": "Notebook directory not found"}

    entries = list_memory_files(notebook_dir, limit=10000)
    stats = {"indexed": 0, "skipped": 0, "errors": 0}

    for key, meta, content in entries:
        try:
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


async def index_all_rooms(db: AsyncSession) -> dict:
    """Scan all rooms and index them."""
    data_dir = get_data_dir()
    rooms_dir = data_dir / "rooms"
    if not rooms_dir.exists():
        return {"rooms": 0, "total_indexed": 0}

    total = 0
    rooms_indexed = 0
    for room_dir in sorted(rooms_dir.iterdir()):
        if room_dir.is_dir():
            stats = await index_room(room_dir.name, db)
            total += stats["indexed"]
            rooms_indexed += 1

    return {"rooms": rooms_indexed, "total_indexed": total}


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

    # Build content text for embedding
    content_text = content or key

    # Generate embedding
    embedding = await asyncio.to_thread(embed_text, content_text)

    # Build value dict
    value = {"text": content} if content else {}

    now = datetime.now(UTC)
    created_by = meta.get("created_by", "filesystem")
    updated_by = meta.get("updated_by", created_by)
    version = meta.get("version", 1)
    tags = meta.get("tags")

    # Parse datetime strings from frontmatter
    created_at = _parse_datetime(meta.get("created_at")) or now
    updated_at = _parse_datetime(meta.get("updated_at")) or now

    # Upsert into DB
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
    existing = result.scalar_one_or_none()

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
        # ISO format
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
