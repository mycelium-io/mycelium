"""
Memory API — persistent namespaced key-value store with semantic vector search.

POST   /rooms/{room}/memory              — create/upsert memories (batch support)
GET    /rooms/{room}/memory              — list memories (prefix filter, pagination)
GET    /rooms/{room}/memory/{key:path}   — get a specific memory by key
DELETE /rooms/{room}/memory/{key:path}   — delete a memory
POST   /rooms/{room}/memory/search       — semantic vector search
POST   /rooms/{room}/memory/subscribe    — subscribe to key pattern changes
DELETE /rooms/{room}/memory/subscribe/{id} — unsubscribe
GET    /rooms/{room}/memory/subscriptions — list active subscriptions
"""

import asyncio
import fnmatch
import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import agent_channel, notify, room_channel
from app.config import settings
from app.database import get_async_session
from app.models import Memory, MemorySubscription, Room
from app.schemas import (
    MemoryBatchCreate,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    SubscriptionCreate,
    SubscriptionRead,
)
from app.services.embedding import embed_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/memory", tags=["memory"])


async def _get_room(room_name: str, db: AsyncSession) -> Room:
    result = await db.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


async def _notify_room_memory_change(
    room_name: str, key: str, updated_by: str, version: int,
) -> None:
    """Broadcast memory change to the room's SSE stream so watchers see it."""
    try:
        parsed = urlparse(settings.DATABASE_URL)
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
        try:
            await notify(
                conn,
                room_channel(room_name),
                {
                    "type": "memory_changed",
                    "room_name": room_name,
                    "key": key,
                    "version": version,
                    "updated_by": updated_by,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("Room NOTIFY for memory change failed: %s", e)


async def _notify_subscribers(
    room_name: str, key: str, updated_by: str, version: int,
) -> None:
    """Check subscriptions and notify matching subscribers via NOTIFY."""
    try:
        parsed = urlparse(settings.DATABASE_URL)
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
        try:
            # Fetch matching subscriptions
            rows = await conn.fetch(
                "SELECT subscriber, key_pattern FROM memory_subscriptions WHERE room_name = $1",
                room_name,
            )
            for row in rows:
                if fnmatch.fnmatch(key, row["key_pattern"]):
                    await notify(
                        conn,
                        agent_channel(row["subscriber"]),
                        {
                            "type": "memory_changed",
                            "room_name": room_name,
                            "key": key,
                            "version": version,
                            "updated_by": updated_by,
                            "created_at": datetime.now(UTC).isoformat(),
                        },
                    )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("Memory subscription notify failed: %s", e)


def _flatten_value(value: dict | str) -> str:
    """Convert a memory value to flat text for embedding."""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


@router.post("", response_model=list[MemoryRead], status_code=201)
async def create_memories(
    room_name: str,
    payload: MemoryBatchCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Create or upsert one or more memories (batch: 1-100 items)."""
    await _get_room(room_name, db)

    results = []
    for item in payload.items:
        # Normalize value to dict
        value = item.value if isinstance(item.value, dict) else {"text": item.value}
        content_text = item.content_text or _flatten_value(item.value)

        # Generate embedding
        embedding = None
        if item.embed:
            embedding = embed_text(content_text)

        # Check for existing memory (upsert)
        existing_result = await db.execute(
            select(Memory).where(
                Memory.room_name == room_name,
                Memory.key == item.key,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.value = value
            existing.content_text = content_text
            existing.embedding = embedding
            existing.updated_by = item.created_by
            existing.version = existing.version + 1
            existing.tags = item.tags
            existing.updated_at = datetime.now(UTC)
            await db.flush()
            await db.refresh(existing)
            results.append(existing)

            asyncio.ensure_future(
                _notify_room_memory_change(room_name, item.key, item.created_by, existing.version)
            )
            asyncio.ensure_future(
                _notify_subscribers(room_name, item.key, item.created_by, existing.version)
            )
        else:
            mem = Memory(
                room_name=room_name,
                key=item.key,
                value=value,
                content_text=content_text,
                embedding=embedding,
                created_by=item.created_by,
                updated_by=item.created_by,
                tags=item.tags,
            )
            db.add(mem)
            await db.flush()
            await db.refresh(mem)
            results.append(mem)

            asyncio.ensure_future(
                _notify_room_memory_change(room_name, item.key, item.created_by, 1)
            )
            asyncio.ensure_future(
                _notify_subscribers(room_name, item.key, item.created_by, 1)
            )

    await db.commit()

    # Check async trigger after writes
    asyncio.ensure_future(_check_async_trigger(room_name, len(payload.items)))

    return [MemoryRead.model_validate(m) for m in results]


async def _check_async_trigger(room_name: str, new_count: int) -> None:
    """Check if an async room's trigger condition is met after memory writes."""
    try:
        from app.services.async_coordination import check_trigger
        await check_trigger(room_name)
    except Exception as e:
        logger.debug("Async trigger check skipped: %s", e)


@router.get("", response_model=list[MemoryRead])
async def list_memories(
    room_name: str,
    prefix: str | None = Query(None, description="Key prefix filter"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_session),
):
    """List memories in a room, optionally filtered by key prefix."""
    await _get_room(room_name, db)

    query = select(Memory).where(Memory.room_name == room_name)
    if prefix:
        query = query.where(Memory.key.startswith(prefix))
    query = query.order_by(Memory.updated_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    memories = list(result.scalars().all())
    return [MemoryRead.model_validate(m) for m in memories]


# ── Search & Subscriptions (must be BEFORE {key:path} catch-all) ──────────

@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(
    room_name: str,
    payload: MemorySearchRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """Semantic vector search over memories in a room."""
    await _get_room(room_name, db)

    query_embedding = embed_text(payload.query)

    # Use pgvector cosine distance operator
    # Note: CAST() instead of :: to avoid SQLAlchemy param binding conflict
    stmt = text("""
        SELECT id, room_name, key, value, content_text, created_by, updated_by,
               version, tags, created_at, updated_at, expires_at,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM memories
        WHERE room_name = :room_name
          AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """)

    result = await db.execute(
        stmt,
        {
            "embedding": str(query_embedding),
            "room_name": room_name,
            "limit": payload.limit,
        },
    )
    rows = result.fetchall()

    results = []
    for row in rows:
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
        )
        results.append(MemorySearchResult(memory=memory_read, similarity=similarity))

    return MemorySearchResponse(results=results, total=len(results))


@router.post("/subscribe", response_model=SubscriptionRead, status_code=201)
async def subscribe(
    room_name: str,
    payload: SubscriptionCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Subscribe to memory change notifications for a key pattern."""
    await _get_room(room_name, db)

    sub = MemorySubscription(
        room_name=room_name,
        subscriber=payload.subscriber,
        key_pattern=payload.key_pattern,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return SubscriptionRead.model_validate(sub)


@router.delete("/subscribe/{subscription_id}", status_code=204)
async def unsubscribe(
    room_name: str,
    subscription_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove a memory subscription."""
    result = await db.execute(
        select(MemorySubscription).where(
            MemorySubscription.id == subscription_id,
            MemorySubscription.room_name == room_name,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await db.delete(sub)
    await db.commit()


@router.get("/subscriptions", response_model=list[SubscriptionRead])
async def list_subscriptions(
    room_name: str,
    db: AsyncSession = Depends(get_async_session),
):
    """List active memory subscriptions for a room."""
    result = await db.execute(
        select(MemorySubscription).where(MemorySubscription.room_name == room_name)
    )
    subs = list(result.scalars().all())
    return [SubscriptionRead.model_validate(s) for s in subs]


# ── Key-path routes (catch-all, must be LAST) ─────────────────────────────

@router.get("/{key:path}", response_model=MemoryRead)
async def get_memory(
    room_name: str,
    key: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Get a specific memory by key."""
    result = await db.execute(
        select(Memory).where(Memory.room_name == room_name, Memory.key == key)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryRead.model_validate(memory)


@router.delete("/{key:path}", status_code=204)
async def delete_memory(
    room_name: str,
    key: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a memory by key."""
    result = await db.execute(
        select(Memory).where(Memory.room_name == room_name, Memory.key == key)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(memory)
    await db.commit()
