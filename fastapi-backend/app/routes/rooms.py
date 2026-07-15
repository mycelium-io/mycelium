# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Room CRUD endpoints."""

import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.models import Room
from app.schemas import RoomCreate, RoomRead
from app.services import coordination
from app.services.filesystem import ensure_room_structure, get_room_dir, remove_room_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms", tags=["rooms"])

# Reserved room names — used by system internals, cannot be created/deleted by users.
RESERVED_ROOMS: frozenset[str] = frozenset()


async def _fetch_mas_id_by_name(room_name: str) -> str | None:
    """GET the MAS list and return the id for the entry matching room_name, or None."""
    url = f"{settings.CFN_MGMT_URL}/api/workspaces/{settings.WORKSPACE_ID}/multi-agentic-systems"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    for system in data.get("systems", []):
        if system.get("name") == room_name:
            return system.get("id")
    return None


async def _sync_create_mas(db_room: Room, session: AsyncSession) -> None:
    """Create a MAS in CFN mgmt plane and store mas_id on the room. Non-fatal."""
    from app.services.metrics import record_cfn_call

    if not settings.CFN_MGMT_URL or not settings.WORKSPACE_ID:
        return
    t0 = time.monotonic()
    try:
        url = (
            f"{settings.CFN_MGMT_URL}/api/workspaces/{settings.WORKSPACE_ID}/multi-agentic-systems"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={
                    "name": db_room.name,
                    # Live mgmt-plane field is `config` (not `mas_config`); apply
                    # mycelium's retry policy so this create path matches _ensure_mas.
                    "config": {
                        "retry_max_attempts": settings.CFN_RETRY_MAX_ATTEMPTS,
                        "validation_score_intervention": settings.CFN_VALIDATION_SCORE_INTERVENTION,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
        record_cfn_call(
            service="mgmt",
            operation="create_mas",
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=resp.status_code,
        )
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
        record_cfn_call(
            service="mgmt",
            operation="create_mas",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        logger.warning("CFN create MAS failed for room %s: %s", db_room.name, exc)


async def _ensure_mas(db_room: Room, session: AsyncSession) -> str | None:
    """Register room with CFN mgmt plane, handling the case where it already exists.

    Returns the mas_id on success, None if CFN is not configured or the call fails.
    On 409 (name already registered), fetches the existing id from the GET list.
    """
    if not settings.CFN_MGMT_URL or not settings.WORKSPACE_ID:
        return None

    base_url = (
        f"{settings.CFN_MGMT_URL}/api/workspaces/{settings.WORKSPACE_ID}/multi-agentic-systems"
    )
    mas_id: str | None = None

    # Set the MAS config at creation so negotiations use mycelium's retry /
    # validation-threshold policy instead of the CFN defaults (retry_max=3,
    # which silently runs a session several times over on a low alignment
    # score: see CFN_RETRY_MAX_ATTEMPTS / CFN_VALIDATION_SCORE_INTERVENTION).
    # The live mgmt-plane field is `config` (MultiAgenticSystemRequest.config);
    # it applies at create and persists (verified via GET on a real MAS). An
    # earlier `mas_config` key was silently dropped; the policy never took.
    create_body = {
        "name": db_room.name,
        "config": {
            "retry_max_attempts": settings.CFN_RETRY_MAX_ATTEMPTS,
            "validation_score_intervention": settings.CFN_VALIDATION_SCORE_INTERVENTION,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(base_url, json=create_body)
            if resp.status_code == 409:
                mas_id = await _fetch_mas_id_by_name(db_room.name)
            else:
                resp.raise_for_status()
                data = resp.json()
                mas_id = data.get("id") or data.get("mas_id")
    except Exception as exc:
        logger.warning("CFN ensure MAS failed for room %s: %s", db_room.name, exc)
        return None

    if mas_id:
        await session.execute(
            update(Room)
            .where(Room.name == db_room.name)
            .values(mas_id=str(mas_id), workspace_id=settings.WORKSPACE_ID)
        )
        await session.commit()
        await session.refresh(db_room)
        logger.info("CFN MAS ensured for room %s: %s", db_room.name, mas_id)

    return mas_id


async def _sync_delete_mas(room: Room) -> None:
    """Delete MAS from CFN mgmt plane. Non-fatal."""
    from app.services.metrics import record_cfn_call

    if not settings.CFN_MGMT_URL or not room.mas_id or not room.workspace_id:
        return
    t0 = time.monotonic()
    try:
        url = (
            f"{settings.CFN_MGMT_URL}/api/workspaces/{room.workspace_id}"
            f"/multi-agentic-systems/{room.mas_id}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(url)
        record_cfn_call(
            service="mgmt",
            operation="delete_mas",
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=resp.status_code,
            error=resp.status_code >= 400,
        )
        logger.info("CFN MAS deleted for room %s: %s", room.name, room.mas_id)
    except Exception as exc:
        record_cfn_call(
            service="mgmt",
            operation="delete_mas",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
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


@router.post("/{room_name}/sync-mas", response_model=RoomRead, status_code=200)
async def sync_room_mas(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Register (or re-register) a room with the CFN mgmt plane.

    Idempotent: if the MAS already exists in CFN, fetches its id from the list
    endpoint rather than erroring. Updates the room's mas_id and workspace_id.
    Returns 409 if CFN is not configured.
    """
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    if not settings.CFN_MGMT_URL or not settings.WORKSPACE_ID:
        raise HTTPException(
            status_code=409,
            detail="CFN not configured — set CFN_MGMT_URL and WORKSPACE_ID",
        )

    mas_id = await _ensure_mas(room, session)
    if not mas_id:
        raise HTTPException(status_code=502, detail="CFN registration failed — check backend logs")

    return room


@router.delete("/{room_name}", status_code=204)
async def delete_room(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a room and cascade to its child session rooms.

    Cleanup order:

      1. Resolve all coordination sessions for this room (display names + IDs).
      2. Tear down in-memory CFN coordination state. Doing this before DB
         deletes prevents in-flight ticks from firing against half-deleted
         state.
      3. Delete the room row — coordination_sessions, participants, and
         messages cascade automatically via FK ON DELETE CASCADE.
      4. Remove the filesystem directory.
      5. Delete the MAS in the CFN mgmt plane (non-fatal, last).
    """
    if room_name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{room_name}' is a reserved system room")

    from app.models import CoordinationSession

    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    coord_result = await session.execute(
        select(CoordinationSession).where(CoordinationSession.parent_room_name == room_name)
    )
    coord_sessions = list(coord_result.scalars().all())
    child_display_names = [c.display_name for c in coord_sessions]

    try:
        await coordination.teardown_for_namespace(room_name, child_display_names)
    except Exception as exc:
        logger.warning("coordination.teardown_for_namespace failed for %s: %s", room_name, exc)

    await session.delete(room)
    await session.commit()

    remove_room_dir(room_name)
    logger.info(
        "Removed room %s and %d child coordination session(s)",
        room_name,
        len(coord_sessions),
    )

    await _sync_delete_mas(room)


@router.get("/{room_name}/negotiation", operation_id="get_negotiation_status")
async def get_negotiation_status(
    room_name: str,
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Return live negotiation state for an active session room.

    Returns ``{"active": false}`` when no negotiation is in progress.
    ``pending_replies`` values are ``"received"`` or ``"waiting"``.
    """
    from app.services.coordination import _cfn_state

    # Don't require a matching Room row here. After migration 0014 (drop
    # session-shadow rows) the session display name (e.g.
    # "exp:session:abc123") no longer exists in `rooms`, so the old 404
    # check broke the CLI's pre-flight snap path. `_cfn_state` is keyed by
    # the same display name the CLI passes in, so a missing entry just
    # means "no active negotiation" — same as for a non-existent room.
    state = _cfn_state.get(room_name)
    if not state:
        return {"active": False}

    result = {
        "active": True,
        "session_id": state.session_id,
        "round": state.current_round,
        "issues": state.issues,
        "issue_options": state.issue_options,
        "current_offer": state.current_offer,
        "pending_replies": {
            h: "received" if v is not None else "waiting" for h, v in state.pending_replies.items()
        },
    }
    # Surface the interim L9 quality metrics the episode already computes, once
    # enough agents have reported confidence. Episode-scoped and provisional --
    # they firm up at consensus. None (thin participation) just omits the block.
    if state.episode is not None:
        from app.services import l9_episode

        metrics = l9_episode.compute_metrics(state.episode)
        if metrics is not None:
            result["metrics"] = metrics
    return result
