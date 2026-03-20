"""Room CRUD endpoints — no Yjs state, no canvas."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Room
from app.schemas import RoomCreate, RoomRead

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

    # Auto-set is_namespace from mode if not explicitly provided
    is_namespace = room.is_namespace
    if is_namespace is None:
        is_namespace = room.mode in ("async", "hybrid")

    db_room = Room(
        name=room.name,
        description=room.description,
        is_public=room.is_public,
        mode=room.mode,
        trigger_config=room.trigger_config,
        is_persistent=room.is_persistent,
        namespace=room.name,
        is_namespace=is_namespace,
    )
    session.add(db_room)
    await session.commit()
    await session.refresh(db_room)
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
    if room.mode not in ("async", "hybrid"):
        raise HTTPException(
            status_code=400, detail="Synthesis only available for async/hybrid rooms"
        )
    if room.coordination_state == "synthesizing":
        raise HTTPException(status_code=409, detail="Synthesis already in progress")

    from app.services.async_coordination import run_synthesis

    result = await run_synthesis(room_name)
    if result is None:
        return {"status": "no_memories", "message": "No new memories to synthesize"}
    return {"status": "complete", **result}


@router.get("/{room_name}/catchup", status_code=200)
async def catchup_room(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Get a briefing for an agent joining a room: latest synthesis + recent activity."""
    from app.models import Memory

    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Get latest synthesis
    synth_result = await session.execute(
        select(Memory)
        .where(Memory.room_name == room_name, Memory.key.startswith("_synthesis/"))
        .order_by(Memory.created_at.desc())
        .limit(1)
    )
    latest_synthesis = synth_result.scalar_one_or_none()

    # Get memories since last synthesis (or all if no synthesis exists)
    recent_query = (
        select(Memory)
        .where(Memory.room_name == room_name)
        .where(Memory.key.not_like("_synthesis/%"))
    )
    if latest_synthesis:
        recent_query = recent_query.where(Memory.created_at > latest_synthesis.created_at)
    recent_query = recent_query.order_by(Memory.created_at.desc()).limit(50)

    recent_result = await session.execute(recent_query)
    recent_memories = list(recent_result.scalars().all())

    # Count total memories
    from sqlalchemy import func

    count_result = await session.execute(
        select(func.count()).select_from(Memory).where(Memory.room_name == room_name)
    )
    total = count_result.scalar() or 0

    # Count contributors
    contributors_result = await session.execute(
        select(Memory.created_by).where(Memory.room_name == room_name).distinct()
    )
    contributors = [r[0] for r in contributors_result.fetchall()]

    return {
        "room": room_name,
        "mode": room.mode,
        "total_memories": total,
        "contributors": contributors,
        "latest_synthesis": {
            "key": latest_synthesis.key,
            "content": latest_synthesis.content_text or latest_synthesis.value,
            "created_at": latest_synthesis.created_at.isoformat(),
        }
        if latest_synthesis
        else None,
        "recent_activity": [
            {
                "key": m.key,
                "created_by": m.created_by,
                "content_text": (m.content_text or "")[:200],
                "created_at": m.created_at.isoformat(),
            }
            for m in recent_memories
        ],
        "memories_since_synthesis": len(recent_memories),
    }


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
