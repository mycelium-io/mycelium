# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Room CRUD endpoints."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.models import Room, Session
from app.schemas import RoomCreate, RoomRead
from app.services import coordination
from app.services.filesystem import ensure_room_structure, get_room_dir, remove_room_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms", tags=["rooms"])

# Reserved room names — used by system internals, cannot be created/deleted by users.
RESERVED_ROOMS = frozenset({"_notebooks"})


async def _sync_create_mas(db_room: Room, session: AsyncSession) -> None:
    """Create a MAS in CFN mgmt plane and store mas_id on the room. Non-fatal."""
    if not settings.CFN_MGMT_URL or not settings.WORKSPACE_ID:
        return
    try:
        url = (
            f"{settings.CFN_MGMT_URL}/api/workspaces/{settings.WORKSPACE_ID}/multi-agentic-systems"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"name": db_room.name})
            resp.raise_for_status()
            data = resp.json()
        mas_id = data.get("id") or data.get("mas_id")
        if mas_id:
            await session.execute(
                update(Room)
                .where(Room.name == db_room.name)
                .values(mas_id=str(mas_id), workspace_id=settings.WORKSPACE_ID)
            )
            await session.commit()
            await session.refresh(db_room)
            logger.info("CFN MAS created for room %s: %s", db_room.name, mas_id)
    except Exception as exc:
        logger.warning("CFN create MAS failed for room %s: %s", db_room.name, exc)


async def _sync_delete_mas(room: Room) -> None:
    """Delete MAS from CFN mgmt plane. Non-fatal."""
    if not settings.CFN_MGMT_URL or not room.mas_id or not room.workspace_id:
        return
    try:
        url = (
            f"{settings.CFN_MGMT_URL}/api/workspaces/{room.workspace_id}"
            f"/multi-agentic-systems/{room.mas_id}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(url)
        logger.info("CFN MAS deleted for room %s: %s", room.name, room.mas_id)
    except Exception as exc:
        logger.warning("CFN delete MAS failed for room %s: %s", room.name, exc)


@router.post("", response_model=RoomRead, status_code=201)
async def create_room(
    room: RoomCreate,
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new room."""
    if room.name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{room.name}' is a reserved system name")

    result = await session.execute(select(Room).where(Room.name == room.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Room already exists")

    db_room = Room(
        name=room.name,
        description=room.description,
        is_public=room.is_public,
        trigger_config=room.trigger_config,
        is_persistent=True,
        namespace=room.name,
        is_namespace=True,
        mas_id=room.mas_id,
        workspace_id=room.workspace_id,
    )
    session.add(db_room)
    await session.commit()
    await session.refresh(db_room)

    # Create filesystem directory with standard namespace structure
    room_dir = get_room_dir(room.name)
    ensure_room_structure(room_dir)
    logger.info("Created room directory: %s", room_dir)

    # Sync MAS with CFN mgmt plane (non-fatal)
    if not db_room.mas_id:
        await _sync_create_mas(db_room, session)

    return db_room


@router.get("", response_model=list[RoomRead])
async def list_rooms(
    session: AsyncSession = Depends(get_async_session),
    skip: int = 0,
    limit: int = 1000,
    name: str | None = None,
):
    """List rooms with optional name filter."""
    query = select(Room).where(Room.is_public == True)  # noqa: E712

    if name:
        query = query.where(Room.name.ilike(f"%{name}%"))

    query = query.offset(skip).limit(limit).order_by(Room.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


@router.get("/{room_name}", response_model=RoomRead)
async def get_room(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Get a room by name."""
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.post("/{room_name}/synthesize", status_code=200)
async def synthesize_room(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Trigger CognitiveEngine async synthesis for a room."""
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if not room.is_namespace:
        raise HTTPException(status_code=400, detail="Synthesis only available for async rooms")
    if room.coordination_state == "synthesizing":
        raise HTTPException(status_code=409, detail="Synthesis already in progress")

    from app.config import LLMUnavailableError, require_llm

    try:
        require_llm()
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    from app.services.async_coordination import run_synthesis

    try:
        result = await run_synthesis(room_name)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        if "authentication failed" in str(exc).lower():
            raise HTTPException(status_code=503, detail=str(exc))
        raise
    if result is None:
        return {"status": "no_memories", "message": "No new memories to synthesize"}
    if result.get("status") == "needs_reindex":
        return {
            "status": "needs_reindex",
            "message": f"Found {result['files_on_disk']} files on disk but none in search index. "
            f"Run 'mycelium reindex {room_name}' to sync.",
            "files_on_disk": result["files_on_disk"],
        }
    return {"status": "complete", **result}


@router.get("/{room_name}/catchup", status_code=200)
async def catchup_room(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Get a briefing for an agent joining a room: latest synthesis + recent activity."""
    from app.services.filesystem import list_memory_files

    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    room_dir = get_room_dir(room_name)

    # Get latest synthesis from filesystem
    synthesis_entries = list_memory_files(room_dir, prefix="_synthesis/", limit=1)
    latest_synthesis_data = None
    if synthesis_entries:
        s_key, s_meta, s_content = synthesis_entries[0]
        latest_synthesis_data = {
            "key": s_key,
            "content": s_content,
            "created_at": s_meta.get("created_at", ""),
        }

    # Get all memory files (excluding synthesis)
    all_entries = list_memory_files(room_dir, limit=1000)
    non_synthesis = [(k, m, c) for k, m, c in all_entries if not k.startswith("_synthesis/")]

    # Filter to recent (after latest synthesis)
    if latest_synthesis_data and latest_synthesis_data.get("created_at"):
        synth_time = str(latest_synthesis_data["created_at"])
        recent_entries = [
            (k, m, c) for k, m, c in non_synthesis if str(m.get("updated_at", "")) > synth_time
        ]
    else:
        recent_entries = non_synthesis

    recent_entries = recent_entries[:50]

    # Gather contributors
    contributors = list({m.get("created_by", "unknown") for _, m, _ in non_synthesis})

    return {
        "room": room_name,
        "mode": room.mode,
        "total_memories": len(non_synthesis),
        "contributors": contributors,
        "latest_synthesis": latest_synthesis_data,
        "recent_activity": [
            {
                "key": k,
                "created_by": m.get("created_by", "unknown"),
                "content_text": c[:200] if c else "",
                "created_at": str(m.get("created_at", "")),
            }
            for k, m, c in recent_entries[:10]
        ],
        "memories_since_synthesis": len(recent_entries),
    }


@router.post("/{room_name}/reindex", status_code=200)
async def reindex_room(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Re-index a room's filesystem into the pgvector search index.

    Scans .mycelium/rooms/{room_name}/ and upserts all markdown files
    into the memories table with fresh embeddings.
    """
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    from app.services.indexer import index_room

    stats = await index_room(room_name, session)
    return {"status": "complete", **stats}


@router.delete("/{room_name}", status_code=204)
async def delete_room(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a room and cascade to its child session rooms.

    Cleanup order is important to avoid stale state firing against
    already-deleted rows:

      1. Enumerate child session rooms (``parent_namespace == room_name``).
      2. Tear down all in-memory CFN coordination state for the namespace
         and its children (cancels pending join timers and active round
         timeouts, posts ``coordination_consensus broken=True`` to any
         SSE subscribers).
      3. Delete child ``Session`` rows, then child ``Room`` rows.
      4. Mark any active child rooms as ``coordination_state="failed"``
         (defensive — if step 3 didn't catch them due to a race, the
         state still reflects reality).
      5. Delete the parent ``Room`` row.
      6. Remove the filesystem directory.
      7. Delete the MAS in the CFN mgmt plane (non-fatal, last so a CFN
         error doesn't block the local cleanup).
    """
    if room_name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{room_name}' is a reserved system room")

    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # 1. Enumerate child session rooms.
    child_result = await session.execute(
        select(Room.name).where(Room.parent_namespace == room_name)
    )
    child_room_names = [r for r in child_result.scalars().all()]

    # 2. Tear down in-memory coordination state for namespace + all children.
    # Do this BEFORE the DB deletes so any in-flight `_run_tick` that resolves
    # against the DB sees the row gone and bails, rather than firing ticks
    # against a half-deleted state.
    try:
        await coordination.teardown_for_namespace(room_name, child_room_names)
    except Exception as exc:
        # Teardown is best-effort cleanup; log but don't block the delete.
        logger.warning("coordination.teardown_for_namespace failed for %s: %s", room_name, exc)

    # 3. Delete child Session rows for every child room (and the parent, in
    #    case anyone joined it directly), then the child Room rows.
    if child_room_names:
        await session.execute(delete(Session).where(Session.room_name.in_(child_room_names)))
    await session.execute(delete(Session).where(Session.room_name == room_name))

    # 4. Defensive: mark any still-existing child rooms as failed before delete
    #    so any concurrent reader sees a consistent state.
    if child_room_names:
        await session.execute(
            update(Room).where(Room.name.in_(child_room_names)).values(coordination_state="failed")
        )
        await session.execute(delete(Room).where(Room.name.in_(child_room_names)))

    # 5. Delete the parent room row.
    await session.delete(room)
    await session.commit()

    # 6. Remove filesystem directory for the parent (children share the parent
    #    namespace's filesystem layout — no separate per-session directory).
    remove_room_dir(room_name)
    logger.info(
        "Removed room %s and %d child session room(s)",
        room_name,
        len(child_room_names),
    )

    # 7. Delete MAS from CFN mgmt plane (non-fatal, last).
    await _sync_delete_mas(room)
