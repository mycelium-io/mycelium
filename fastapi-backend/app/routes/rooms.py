# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Room CRUD endpoints. Rooms are folders; metadata lives in a sidecar file."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.bus import app_channel, bus
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
from app.services.persister import TRANSCRIPT_FILENAME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms", tags=["rooms"])

# Reserved room names — used by system internals, cannot be created/deleted by users.
RESERVED_ROOMS: frozenset[str] = frozenset()


def _room_read(room_name: str) -> RoomRead | None:
    meta = read_room_meta(room_name)
    if meta is None:
        return None
    return RoomRead(**meta)


def _last_activity(room: RoomRead) -> datetime:
    """When a room was last active: its transcript's mtime, or ``created_at``.

    The transcript (``log/transcript.jsonl``) is appended to on every message
    (see ``persister.py``), so its mtime is a cheap proxy for "last message
    time" without parsing the file. Rooms with no messages yet fall back to
    creation time.
    """
    transcript_path = get_room_dir(room.name) / TRANSCRIPT_FILENAME
    try:
        return datetime.fromtimestamp(transcript_path.stat().st_mtime, tz=UTC)
    except OSError:
        return room.created_at


@router.post("", response_model=RoomRead, status_code=201)
async def create_room(room: RoomCreate):
    """Create a new room (directory + metadata sidecar)."""
    if room.name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{room.name}' is a reserved system name")
    if room_exists(room.name):
        # Idempotent: re-creating an existing room is a no-op on disk but
        # (re)ensures its SLIM channel, so a caller can recover a channel-less
        # room without a full backend restart. Metadata is left untouched.
        await room_channels.manager.provision(room.name)
        existing = _room_read(room.name)
        if existing is None:
            raise HTTPException(status_code=404, detail="Room not found")
        return existing

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

    # Room = SLIM channel: provision the group channel with the backend
    # as moderator. Best-effort — a missing/unreachable node leaves the room a
    # pure memory namespace rather than failing creation.
    await room_channels.manager.provision(room.name, workspace=room.workspace_id)

    result = _room_read(room.name)
    assert result is not None  # just created

    # Push to the global app channel so every open UI's room list updates live.
    bus.publish(
        app_channel(),
        {
            "type": "room_created",
            "room_name": room.name,
            "mas_id": room.mas_id,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
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
    visible.sort(key=_last_activity, reverse=True)
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

    bus.publish(app_channel(), {"type": "room_deleted", "room_name": room_name})
