# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Memory API — persistent namespaced key-value store with semantic search.

Backed by markdown files (canonical) plus a local JSONL embedding index — no
database.

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
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.bus import agent_channel, bus, room_channel
from app.schemas import (
    MemoryBatchCreate,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    SubscriptionCreate,
    SubscriptionRead,
)
from app.services import local_state, search_index
from app.services.embedding import embed_text
from app.services.filesystem import (
    delete_memory_file,
    get_room_dir,
    list_memory_files,
    read_memory_file,
    room_exists,
    value_to_content,
    write_memory_file,
)
from app.services.search_index import stable_memory_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/memory", tags=["memory"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _flatten_value(value: dict | str) -> str:
    """Convert a memory value to flat text for embedding."""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


def _reconstruct_value(meta: dict, content: str) -> dict | str:
    """Rebuild the API ``value`` from a memory file.

    Structured values (dicts with keys beyond ``text``) are round-tripped via
    the ``value`` frontmatter key written at ``create`` time; pure-text values
    are reconstructed from the markdown body.
    """
    if "value" in meta and meta["value"] is not None:
        return meta["value"]
    return {"text": content} if content else {}


def _memory_read_from_file(room_name: str, key: str, meta: dict, content: str) -> MemoryRead:
    """Build a MemoryRead from a memory file's frontmatter + body."""
    now = datetime.now(UTC)
    return MemoryRead(
        id=stable_memory_id(room_name, key),
        room_name=room_name,
        key=key,
        value=_reconstruct_value(meta, content),
        content_text=content or None,
        created_by=meta.get("created_by", "unknown"),
        updated_by=meta.get("updated_by"),
        version=meta.get("version", 1),
        tags=meta.get("tags"),
        created_at=meta.get("created_at", now),
        updated_at=meta.get("updated_at", now),
        file_path=f"rooms/{room_name}/{key}.md",
    )


def _notify_change(room_name: str, key: str, updated_by: str, version: int) -> None:
    """Publish a memory-change event to the room channel and matching subscribers."""
    payload = {
        "type": "memory_changed",
        "room_name": room_name,
        "key": key,
        "version": version,
        "updated_by": updated_by,
        "created_at": datetime.now(UTC).isoformat(),
    }
    bus.publish(room_channel(room_name), payload)
    for sub in local_state.list_subscriptions(room_name):
        if fnmatch.fnmatch(key, sub.key_pattern):
            bus.publish(agent_channel(sub.subscriber), payload)


@router.post("", response_model=list[MemoryRead], status_code=201)
async def create_memories(room_name: str, payload: MemoryBatchCreate):
    """Create or upsert one or more memories (batch: 1-100 items).

    Writes markdown files to ``.mycelium/rooms/{room_name}/`` and updates the
    JSONL search index. Conflict policy: last-write-wins ordered by the memory's
    incrementing ``version``; a write against a stale ``base_version`` is
    rejected with the current content + who/when last wrote it.
    """
    _require_room(room_name)
    room_dir = get_room_dir(room_name)

    from app.services.metrics import record_memory_write

    results: list[MemoryRead] = []
    write_metrics: list[bool] = []
    for item in payload.items:
        value = item.value if isinstance(item.value, dict) else {"text": item.value}
        content_text = item.content_text or _flatten_value(item.value)
        body = value_to_content(value)

        existing = read_memory_file(room_dir, item.key)
        existing_meta = existing[0] if existing else {}
        current_version = existing_meta.get("version", 0) if existing else 0

        # Conflict check: a supplied base_version must match what's on disk.
        if item.base_version is not None and item.base_version != current_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "stale_base",
                    "message": (
                        f"Write for '{item.key}' expected version {item.base_version} "
                        f"but current version is {current_version}"
                    ),
                    "key": item.key,
                    "current_version": current_version,
                    "current_content": existing[1] if existing else None,
                    "updated_by": existing_meta.get("updated_by")
                    or existing_meta.get("created_by"),
                    "updated_at": existing_meta.get("updated_at"),
                },
            )

        now = datetime.now(UTC)
        if existing:
            new_version = current_version + 1
            created_by = existing_meta.get("created_by", item.created_by)
            created_at = existing_meta.get("created_at", now)
        else:
            new_version = 1
            created_by = item.created_by
            created_at = now

        # Persist structured values into frontmatter so non-text keys survive
        # the round-trip (the markdown body only carries the ``text``/rendering).
        extra_meta: dict[str, Any] = {}
        if set(value.keys()) != {"text"}:
            extra_meta["value"] = value

        write_memory_file(
            room_dir,
            item.key,
            body,
            created_by=created_by,
            updated_by=item.created_by,
            version=new_version,
            tags=item.tags,
            created_at=created_at if isinstance(created_at, datetime) else now,
            updated_at=now,
            extra_meta=extra_meta or None,
        )

        embedding = None
        if item.embed:
            embedding = await asyncio.to_thread(embed_text, content_text)
        write_metrics.append(item.embed)

        search_index.upsert(
            room_name,
            {
                "key": item.key,
                "room_name": room_name,
                "content_text": content_text,
                "embedding": embedding,
                "value": value if extra_meta else None,
                "created_by": created_by,
                "updated_by": item.created_by,
                "version": new_version,
                "tags": item.tags,
                "created_at": created_at.isoformat()
                if isinstance(created_at, datetime)
                else str(created_at),
                "updated_at": now.isoformat(),
                "file_path": f"rooms/{room_name}/{item.key}.md",
            },
        )

        results.append(
            MemoryRead(
                id=stable_memory_id(room_name, item.key),
                room_name=room_name,
                key=item.key,
                value=value,
                content_text=content_text,
                created_by=created_by,
                updated_by=item.created_by,
                version=new_version,
                tags=item.tags,
                created_at=created_at if isinstance(created_at, datetime) else now,
                updated_at=now,
                file_path=f"rooms/{room_name}/{item.key}.md",
            )
        )
        _notify_change(room_name, item.key, item.created_by, new_version)

    for embedded in write_metrics:
        record_memory_write(scope="namespace", embedded=embedded)

    return results


@router.get("")
async def list_memories(
    room_name: str,
    request: Request,
    prefix: str | None = Query(None, description="Key prefix filter"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List memories in a room (from the filesystem).

    Supports ETag / If-None-Match for efficient sync — returns 304 if nothing
    changed.
    """
    _require_room(room_name)
    room_dir = get_room_dir(room_name)
    file_entries = list_memory_files(room_dir, prefix=prefix, limit=limit + offset)

    latest_ts = max((meta.get("updated_at", "") for _, meta, _ in file_entries), default="")
    etag = '"' + hashlib.md5(str(latest_ts).encode()).hexdigest() + '"' if latest_ts else '"empty"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    page = file_entries[offset : offset + limit]
    memories = [
        _memory_read_from_file(room_name, key, meta, content) for key, meta, content in page
    ]

    from fastapi.encoders import jsonable_encoder

    return Response(
        content=json.dumps(jsonable_encoder(memories)),
        media_type="application/json",
        headers={"ETag": etag},
    )


# ── Search & Subscriptions (must be BEFORE {key:path} catch-all) ──────────


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(room_name: str, payload: MemorySearchRequest):
    """Semantic vector search over memories in a room.

    Brute-force cosine over the room's local JSONL index.
    """
    from app.services.metrics import record_memory_search

    t0 = time.monotonic()
    _require_room(room_name)

    query_embedding = await asyncio.to_thread(embed_text, payload.query)
    hits = search_index.search(
        room_name,
        query_embedding,
        limit=payload.limit,
        min_similarity=payload.min_similarity,
    )

    now = datetime.now(UTC)
    results = []
    for rec, similarity in hits:
        value = rec.get("value")
        if value is None:
            value = {"text": rec.get("content_text")} if rec.get("content_text") else {}
        memory_read = MemoryRead(
            id=stable_memory_id(room_name, rec["key"]),
            room_name=room_name,
            key=rec["key"],
            value=value,
            content_text=rec.get("content_text"),
            created_by=rec.get("created_by", "unknown"),
            updated_by=rec.get("updated_by"),
            version=rec.get("version", 1),
            tags=rec.get("tags"),
            created_at=rec.get("created_at", now),
            updated_at=rec.get("updated_at", now),
            file_path=rec.get("file_path"),
        )
        results.append(MemorySearchResult(memory=memory_read, similarity=similarity))

    record_memory_search(
        duration_ms=(time.monotonic() - t0) * 1000,
        results_returned=len(results),
    )
    return MemorySearchResponse(results=results, total=len(results))


@router.post("/subscribe", response_model=SubscriptionRead, status_code=201)
async def subscribe(room_name: str, payload: SubscriptionCreate):
    """Subscribe to memory change notifications for a key pattern."""
    _require_room(room_name)
    sub = local_state.StoredSubscription(
        room_name=room_name,
        subscriber=payload.subscriber,
        key_pattern=payload.key_pattern,
    )
    local_state.add_subscription(sub)
    return SubscriptionRead.model_validate(sub)


@router.delete("/subscribe/{subscription_id}", status_code=204)
async def unsubscribe(room_name: str, subscription_id: UUID):
    """Remove a memory subscription."""
    if not local_state.remove_subscription(room_name, subscription_id):
        raise HTTPException(status_code=404, detail="Subscription not found")


@router.get("/subscriptions", response_model=list[SubscriptionRead])
async def list_subscriptions(room_name: str):
    """List active memory subscriptions for a room."""
    return [SubscriptionRead.model_validate(s) for s in local_state.list_subscriptions(room_name)]


# ── Key-path routes (catch-all, must be LAST) ─────────────────────────────


@router.get("/{key:path}", response_model=MemoryRead)
async def get_memory(room_name: str, key: str):
    """Get a specific memory by key (from the filesystem)."""
    _require_room(room_name)
    room_dir = get_room_dir(room_name)
    file_data = read_memory_file(room_dir, key)
    if not file_data:
        raise HTTPException(status_code=404, detail="Memory not found")
    meta, content = file_data
    return _memory_read_from_file(room_name, key, meta, content)


@router.delete("/{key:path}", status_code=204)
async def delete_memory(room_name: str, key: str):
    """Delete a memory by key. Removes the file and its search-index entry."""
    room_dir = get_room_dir(room_name)
    file_deleted = delete_memory_file(room_dir, key)
    index_deleted = search_index.remove(room_name, key)
    if not file_deleted and not index_deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
