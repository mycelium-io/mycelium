"""
Notebook API — agent-private memory scoped by handle.

Convenience routes that delegate to the memory system with scope="notebook".
Notebooks don't require a room — they use a system namespace "_notebooks".

POST   /notebook/{handle}/memory           — write a notebook memory
GET    /notebook/{handle}/memory           — list notebook memories
GET    /notebook/{handle}/memory/{key:path} — get a specific notebook memory
DELETE /notebook/{handle}/memory/{key:path} — delete a notebook memory
POST   /notebook/{handle}/memory/search    — semantic search in notebook
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Memory, Room
from app.schemas import (
    MemoryBatchCreate,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
)
from app.services.embedding import embed_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notebook/{handle}", tags=["notebook"])

# System namespace for notebook memories — auto-created on first use.
NOTEBOOK_ROOM = "_notebooks"


async def _ensure_notebook_room(db: AsyncSession) -> Room:
    """Get or create the system _notebooks room."""
    result = await db.execute(select(Room).where(Room.name == NOTEBOOK_ROOM))
    room = result.scalar_one_or_none()
    if room:
        return room

    room = Room(
        name=NOTEBOOK_ROOM,
        description="System namespace for agent notebooks",
        is_public=False,
        mode="async",
        is_namespace=True,
        is_persistent=True,
        namespace=NOTEBOOK_ROOM,
    )
    db.add(room)
    await db.flush()
    await db.refresh(room)
    return room


def _flatten_value(value: dict | str) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


@router.post("/memory", response_model=list[MemoryRead], status_code=201)
async def write_notebook(
    handle: str,
    payload: MemoryBatchCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Write memories to an agent's private notebook."""
    await _ensure_notebook_room(db)

    results = []
    for item in payload.items:
        value = item.value if isinstance(item.value, dict) else {"text": item.value}
        content_text = item.content_text or _flatten_value(item.value)

        embedding = None
        if item.embed:
            embedding = await asyncio.to_thread(embed_text, content_text)

        # Upsert scoped to this agent's notebook
        existing_result = await db.execute(
            select(Memory).where(
                Memory.room_name == NOTEBOOK_ROOM,
                Memory.key == item.key,
                Memory.scope == "notebook",
                Memory.owner_handle == handle,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.value = value
            existing.content_text = content_text
            existing.embedding = embedding
            existing.updated_by = handle
            existing.version = existing.version + 1
            existing.tags = item.tags
            existing.updated_at = datetime.now(UTC)
            await db.flush()
            await db.refresh(existing)
            results.append(existing)
        else:
            mem = Memory(
                room_name=NOTEBOOK_ROOM,
                key=item.key,
                value=value,
                content_text=content_text,
                embedding=embedding,
                created_by=handle,
                updated_by=handle,
                tags=item.tags,
                scope="notebook",
                owner_handle=handle,
            )
            db.add(mem)
            await db.flush()
            await db.refresh(mem)
            results.append(mem)

    await db.commit()
    return [MemoryRead.model_validate(m) for m in results]


@router.get("/memory", response_model=list[MemoryRead])
async def list_notebook(
    handle: str,
    prefix: str | None = Query(None, description="Key prefix filter"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_session),
):
    """List an agent's notebook memories."""
    query = (
        select(Memory)
        .where(
            Memory.room_name == NOTEBOOK_ROOM,
            Memory.scope == "notebook",
            Memory.owner_handle == handle,
        )
        .order_by(Memory.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if prefix:
        query = query.where(Memory.key.startswith(prefix))

    result = await db.execute(query)
    return [MemoryRead.model_validate(m) for m in result.scalars().all()]


@router.post("/memory/search", response_model=MemorySearchResponse)
async def search_notebook(
    handle: str,
    payload: MemorySearchRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """Semantic search within an agent's notebook."""
    from sqlalchemy import text

    query_embedding = await asyncio.to_thread(embed_text, payload.query)

    stmt = text("""
        SELECT id, room_name, key, value, content_text, created_by, updated_by,
               version, tags, created_at, updated_at, expires_at, scope, owner_handle,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM memories
        WHERE room_name = :room_name
          AND scope = 'notebook'
          AND owner_handle = :handle
          AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """)

    result = await db.execute(
        stmt,
        {
            "embedding": str(query_embedding),
            "room_name": NOTEBOOK_ROOM,
            "handle": handle,
            "limit": payload.limit,
        },
    )

    results = []
    for row in result.fetchall():
        similarity = float(row.similarity)
        if similarity < payload.min_similarity:
            continue
        memory_read = MemoryRead(
            id=row.id,
            room_name=row.room_name,
            key=row.key,
            value=row.value,
            content_text=row.content_text,
            created_by=row.created_by,
            updated_by=row.updated_by,
            version=row.version,
            tags=row.tags,
            created_at=row.created_at,
            updated_at=row.updated_at,
            scope=row.scope,
            owner_handle=row.owner_handle,
        )
        results.append(MemorySearchResult(memory=memory_read, similarity=similarity))

    return MemorySearchResponse(results=results, total=len(results))


@router.get("/memory/{key:path}", response_model=MemoryRead)
async def get_notebook_memory(
    handle: str,
    key: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Get a specific notebook memory by key."""
    result = await db.execute(
        select(Memory).where(
            Memory.room_name == NOTEBOOK_ROOM,
            Memory.key == key,
            Memory.scope == "notebook",
            Memory.owner_handle == handle,
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Notebook memory not found")
    return MemoryRead.model_validate(memory)


@router.delete("/memory/{key:path}", status_code=204)
async def delete_notebook_memory(
    handle: str,
    key: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a notebook memory by key."""
    result = await db.execute(
        select(Memory).where(
            Memory.room_name == NOTEBOOK_ROOM,
            Memory.key == key,
            Memory.scope == "notebook",
            Memory.owner_handle == handle,
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Notebook memory not found")
    await db.delete(memory)
    await db.commit()
