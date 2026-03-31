# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Room CRUD endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Room
from app.schemas import RoomCreate, RoomRead
from app.services.filesystem import ensure_room_structure, get_room_dir, remove_room_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms", tags=["rooms"])

# Reserved room names — used by system internals, cannot be created/deleted by users.
RESERVED_ROOMS = frozenset({"_notebooks"})


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
    )
    session.add(db_room)
    await session.commit()
    await session.refresh(db_room)

    # Create filesystem directory with standard namespace structure
    room_dir = get_room_dir(room.name)
    ensure_room_structure(room_dir)
    logger.info("Created room directory: %s", room_dir)

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
    """Delete a room by name."""
    if room_name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{room_name}' is a reserved system room")

    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    await session.delete(room)
    await session.commit()

    # Remove filesystem directory
    remove_room_dir(room_name)
    logger.info("Removed room directory for: %s", room_name)
