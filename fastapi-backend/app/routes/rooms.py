# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Room CRUD endpoints. Rooms are folders; metadata lives in a sidecar file."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.schemas import RoomCreate, RoomRead
from app.services import room_channels
from app.services.filesystem import (
    ensure_room_structure,
    get_room_dir,
    list_room_names,
    read_room_meta,
    remove_room_dir,
    room_exists,
    write_room_meta,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms", tags=["rooms"])

# Reserved room names — used by system internals, cannot be created/deleted by users.
RESERVED_ROOMS: frozenset[str] = frozenset()


def _room_read(room_name: str) -> RoomRead | None:
    meta = read_room_meta(room_name)
    if meta is None:
        return None
    return RoomRead(**meta)


@router.post("", response_model=RoomRead, status_code=201)
async def create_room(room: RoomCreate):
    """Create a new room (directory + metadata sidecar)."""
    if room.name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{room.name}' is a reserved system name")
    if room_exists(room.name):
        raise HTTPException(status_code=400, detail="Room already exists")

    room_dir = get_room_dir(room.name)
    ensure_room_structure(room_dir)
    write_room_meta(
        room.name,
        {
            "name": room.name,
            "description": room.description,
            "is_public": room.is_public,
            "is_persistent": True,
            "mas_id": room.mas_id,
            "workspace_id": room.workspace_id,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    logger.info("Created room directory: %s", room_dir)

    # Room = SLIM channel (Step 3): provision the group channel with the backend
    # as moderator. Best-effort — a missing/unreachable node leaves the room a
    # pure memory namespace rather than failing creation.
    await room_channels.manager.provision(room.name, workspace=room.workspace_id)

    result = _room_read(room.name)
    assert result is not None  # just created
    return result


@router.get("", response_model=list[RoomRead])
async def list_rooms(
    skip: int = 0,
    limit: int = 1000,
    name: str | None = None,
    include_sessions: bool = False,
):
    """List rooms. ``include_sessions`` is accepted for compat but is a no-op."""
    _ = include_sessions
    rooms = [_room_read(n) for n in list_room_names()]
    visible = [r for r in rooms if r is not None and r.is_public]
    if name:
        visible = [r for r in visible if name.lower() in r.name.lower()]
    visible.sort(key=lambda r: r.created_at, reverse=True)
    return visible[skip : skip + limit]


@router.get("/{room_name}", response_model=RoomRead)
async def get_room(room_name: str):
    """Get a room by name."""
    result = _room_read(room_name)
    if result is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return result


@router.post("/{room_name}/reindex", status_code=200)
async def reindex_room(room_name: str):
    """Re-index a room's filesystem into the JSONL search index."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")

    from app.services.indexer import index_room

    stats = await index_room(room_name)
    return {"status": "complete", **stats}


@router.delete("/{room_name}", status_code=204)
async def delete_room(room_name: str):
    """Delete a room and its filesystem directory."""
    if room_name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{room_name}' is a reserved system room")
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")

    await room_channels.manager.close(room_name)
    remove_room_dir(room_name)
    logger.info("Removed room %s", room_name)
