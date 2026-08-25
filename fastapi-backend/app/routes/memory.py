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
from app.services import actor, links, local_state, memory_sync, search_index
from app.services.embedding import embed_text
from app.services.filesystem import (
    EPISODE_META,
    MANAGED_META,
    SYSTEM_META,
    delete_memory_file,
    get_room_dir,
    list_memory_files,
    parse_timestamp,
    read_memory_file,
    recover_timestamps,
    room_exists,
    system_meta,
    unmanaged_meta,
    value_to_content,
    write_memory_file,
)
from app.services.search_index import stable_memory_id
from app.services.tasks import is_board_row, mint_episode_urn

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
    """Build a MemoryRead from a memory file's frontmatter + body.

    Stamps come from :func:`recover_timestamps`, which falls back to the file's
    mtime rather than to read time — a memory whose frontmatter lost its
    ``updated_at`` would otherwise report a different, always-newest timestamp on
    every read and drift to the end of any time-ordered view.
    """
    created_at, updated_at = recover_timestamps(meta, get_room_dir(room_name) / f"{key}.md")
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
        meta=unmanaged_meta(meta) or None,
        episode=meta.get(EPISODE_META),
        expandable=links.is_expandable(meta),
        created_at=created_at,
        updated_at=updated_at,
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


# Strong refs for the fire-and-forget broadcasts below — an unreferenced
# asyncio task can be garbage-collected mid-flight (mirrors
# RoomChannelManager._tasks / PlanSyncEngine._tasks).
_broadcast_tasks: set[asyncio.Task[Any]] = set()


def _broadcast_memory_write(
    room_name: str,
    *,
    key: str,
    content: str,
    version: int,
    base_version: int | None,
    created_by: str,
    updated_by: str,
    updated_at: str,
) -> None:
    """Schedule an ``extraction`` knowledge push mirroring a direct memory write.

    Fire-and-forget: the write has already landed on disk and in the index, so a
    broadcast failure must never surface as a write failure. A room with no live
    channel is a silent no-op, same as the plan-sync consumer.
    """
    from app.services import room_channels

    managed = room_channels.manager.get(room_name)
    if managed is None:
        return
    write = memory_sync.KnowledgeWrite(
        key=key,
        content=content,
        version=version,
        base_version=base_version,
        created_by=created_by,
        updated_by=updated_by,
        updated_at=updated_at,
    )
    recipients = room_channels.manager.members(room_name)
    task = asyncio.create_task(_send_memory_write_knowledge(room_name, managed, write, recipients))
    _broadcast_tasks.add(task)
    task.add_done_callback(_broadcast_tasks.discard)


async def _send_memory_write_knowledge(
    room_name: str, managed: Any, write: memory_sync.KnowledgeWrite, recipients: list[str]
) -> None:
    """Broadcast ``write`` on the room channel and record it locally.

    ``ingest_local`` makes the transcript/UI bus see it even if SLIM never loops
    the broadcast back; it only records, so it cannot re-enter this write path.
    """
    from app.services.l9_slim import serialize_content

    envelope = memory_sync.build_knowledge_envelope(
        room=room_name,
        write=write,
        recipients=recipients,
        subkind=memory_sync.MEMORY_WRITE_SUBKIND,
    )
    content = serialize_content(envelope, extra={"content": f"memory updated → {write.key}"})
    try:
        await managed.channel.send(envelope, extra={"content": content["content"]})
    except Exception:
        logger.warning("failed to broadcast memory-write knowledge on room %s", room_name)
    if managed.persister is not None:
        managed.persister.ingest_local(envelope, content)


@router.post("", response_model=list[MemoryRead], status_code=201)
async def create_memories(room_name: str, payload: MemoryBatchCreate, request: Request):
    """Create or upsert one or more memories (batch: 1-100 items).

    Writes markdown files to ``.mycelium/rooms/{room_name}/`` and updates the
    JSONL search index. Conflict policy: last-write-wins ordered by the memory's
    incrementing ``version``; a write against a stale ``base_version`` is
    rejected with the current content + who/when last wrote it.
    """
    for item in payload.items:
        item.created_by = actor.bind_actor(request, item.created_by, field="created_by")
    return await upsert_memories(room_name, payload)


async def upsert_memories(
    room_name: str,
    payload: MemoryBatchCreate,
    *,
    notify: bool = True,
    system: dict[str, Any] | None = None,
) -> list[MemoryRead]:
    """The write itself, with ``created_by`` already resolved to its true author.

    Split from the route so backend-owned writers (the synthesizer, an engine
    manifest) reuse the one correct upsert without routing their actor through a
    request body they never had.

    ``notify=False`` is for writes that are not news — a custody heartbeat
    re-dating a lease it already holds.  The file, the index and the link graph
    are all updated exactly as usual; what is skipped is telling the room, which
    a loop running every few seconds must not do.

    ``system`` sets the store-owned frontmatter in :data:`SYSTEM_META` — today
    just the ``episode`` a task is bound to.  An in-process parameter has
    no wire form, so nothing over HTTP can point a row at a thread it was never
    part of; the same key stays ignored in ``MemoryCreate.meta``.

    It is **write-once**: a value already on the row wins, so a task stays bound
    to the thread its history is in for the row's whole life.
    """
    _require_room(room_name)
    if system and not set(system) <= SYSTEM_META:
        raise ValueError(
            f"system meta outside {sorted(SYSTEM_META)}: {sorted(set(system) - SYSTEM_META)}"
        )
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
            created_at = parse_timestamp(existing_meta.get("created_at")) or now
        else:
            new_version = 1
            created_by = item.created_by
            created_at = now

        # Frontmatter the store doesn't manage is user data — carry it forward so
        # a content update doesn't silently drop a page's `expandable: true` or
        # its typed relations — then overlay whatever this write supplies.
        extra_meta: dict[str, Any] = unmanaged_meta(existing_meta)
        if item.meta:
            extra_meta.update({k: v for k, v in item.meta.items() if k not in MANAGED_META})

        # The store's own minted keys, which nothing here recomputes. ``system``
        # supplies one; what the row already carries wins, so the binding is
        # write-once: a field write cannot silently unbind a row from its thread,
        # and a later writer cannot move it onto a different one.
        if system:
            extra_meta.update(system)
        extra_meta.update(system_meta(existing_meta))

        # Every board row is a task with its own thread. If this write creates
        # one in a board namespace and nothing has already bound it, mint its
        # episode now — so a task, a decision or a blocked item carries a thread
        # from the moment it exists, not only once a negotiation happens inside
        # it. The merge above is write-once (an existing binding won), so this
        # only ever fires on creation and each row gets a distinct URN.
        if EPISODE_META not in extra_meta and is_board_row(item.key):
            extra_meta[EPISODE_META] = mint_episode_urn(room_name)

        # Persist structured values into frontmatter so non-text keys survive
        # the round-trip (the markdown body only carries the ``text``/rendering).
        structured = set(value.keys()) != {"text"}
        if structured:
            extra_meta["value"] = value

        write_memory_file(
            room_dir,
            item.key,
            body,
            created_by=created_by,
            updated_by=item.created_by,
            version=new_version,
            tags=item.tags,
            created_at=created_at,
            updated_at=now,
            extra_meta=extra_meta or None,
        )

        embedding = None
        if item.embed:
            embedding = await asyncio.to_thread(embed_text, content_text)
        else:
            # A metadata-only write (a claim, a renewal) leaves the prose alone,
            # so it must leave the vector alone too. The index record is replaced
            # wholesale, so not carrying the old embedding forward would quietly
            # drop the memory out of semantic search.
            embedding = search_index.embedding_for(room_name, item.key)
        write_metrics.append(item.embed)

        search_index.upsert(
            room_name,
            {
                "key": item.key,
                "room_name": room_name,
                "content_text": content_text,
                "embedding": embedding,
                "value": value if structured else None,
                "created_by": created_by,
                "updated_by": item.created_by,
                "version": new_version,
                "tags": item.tags,
                "meta": unmanaged_meta(extra_meta) or None,
                "episode": extra_meta.get(EPISODE_META),
                "expandable": links.is_expandable(extra_meta),
                "created_at": created_at.isoformat(),
                "updated_at": now.isoformat(),
                "file_path": f"rooms/{room_name}/{item.key}.md",
            },
        )
        links.upsert(room_name, item.key, extra_meta, body)

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
                meta=unmanaged_meta(extra_meta) or None,
                episode=extra_meta.get(EPISODE_META),
                expandable=links.is_expandable(extra_meta),
                created_at=created_at,
                updated_at=now,
                file_path=f"rooms/{room_name}/{item.key}.md",
            )
        )
        if not notify:
            continue
        _notify_change(room_name, item.key, item.created_by, new_version)
        _broadcast_memory_write(
            room_name,
            key=item.key,
            content=body.rstrip("\n") + "\n",
            version=new_version,
            base_version=current_version if existing else None,
            created_by=created_by,
            updated_by=item.created_by,
            updated_at=now.isoformat(),
        )
        # A board row appearing for the first time is the room filing work: raise
        # a `filed` notice into the timeline, naming the task, its kind (so it
        # reads "New decision" not always "New task") and who it is for. Only on
        # creation — a later write is a state change, carried by its own verb.
        if not existing and is_board_row(item.key):
            from app.services.room_channels import manager

            first_line = next((ln for ln in content_text.splitlines() if ln.strip()), item.key)
            await manager.raise_notice(
                room_name,
                subkind="filed",
                key=item.key,
                title=first_line.lstrip("# ").strip(),
                episode=extra_meta.get(EPISODE_META),
                by=str(created_by).lstrip("@"),
                kind=extra_meta.get("kind"),
                **({"for": str(extra_meta["assignee"])} if extra_meta.get("assignee") else {}),
            )

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

    latest_ts = max((str(meta.get("updated_at", "")) for _, meta, _ in file_entries), default="")
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

    room_dir = get_room_dir(room_name)
    results = []
    for rec, similarity in hits:
        value = rec.get("value")
        if value is None:
            value = {"text": rec.get("content_text")} if rec.get("content_text") else {}
        # An index record predating a stamp resolves against the file it points
        # at, never against read time (see _memory_read_from_file).
        created_at, updated_at = recover_timestamps(rec, room_dir / f"{rec['key']}.md")
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
            meta=rec.get("meta") or None,
            episode=rec.get(EPISODE_META),
            expandable=bool(rec.get("expandable")),
            created_at=created_at,
            updated_at=updated_at,
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
    links.remove(room_name, key)
    if not file_deleted and not index_deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
