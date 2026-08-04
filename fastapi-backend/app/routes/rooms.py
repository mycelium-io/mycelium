# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

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
RESERVED_ROOMS: frozenset[str] = frozenset()


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
        is_persistent=True,
        namespace=room.name,
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

    return db_room


@router.get("", response_model=list[RoomRead])
async def list_rooms(
    session: AsyncSession = Depends(get_async_session),
    skip: int = 0,
    limit: int = 1000,
    name: str | None = None,
    include_sessions: bool = False,
):
    """List rooms.

    Sessions live in ``coordination_sessions`` and are not surfaced here. The
    ``include_sessions`` parameter is accepted for backward-compatible URLs
    but is a no-op.
    """
    _ = include_sessions  # accepted for compat; nothing to filter
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
    """Delete a room and its filesystem directory.

    Any child rows (messages, presence) cascade automatically via FK
    ON DELETE CASCADE.
    """
    if room_name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{room_name}' is a reserved system room")

    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    await session.delete(room)
    await session.commit()

    remove_room_dir(room_name)
    logger.info("Removed room %s", room_name)
