# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Sessions API — tracks agent presence in rooms.

POST   /rooms/{room}/sessions       — join a room (auto-spawns session if room is a namespace)
POST   /rooms/{room}/sessions/spawn — explicitly spawn a negotiation session within a namespace
GET    /rooms/{room}/sessions       — list who is in a room
DELETE /rooms/{room}/sessions/{id}  — leave a room
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import notify, room_channel
from app.config import settings
from app.database import get_async_session
from app.models import CoordinationSession, Participant, Room
from app.routes.rooms import _sync_create_mas
from app.schemas import (
    CoordinationSessionRead,
    ParticipantCreate,
    ParticipantListResponse,
    ParticipantRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/sessions", tags=["sessions"])


async def _upsert_room(room_name: str, session: AsyncSession) -> Room:
    """Get existing room or create it (for coordination auto-join)."""
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        room = Room(
            name=room_name,
            is_public=True,
            namespace=room_name,
            is_namespace=True,
        )
        session.add(room)
        try:
            await session.commit()
        except Exception:
            # Race: another request created it first
            await session.rollback()
            result = await session.execute(select(Room).where(Room.name == room_name))
            room = result.scalar_one_or_none()
            if not room:
                raise HTTPException(status_code=500, detail="Failed to create room")
        else:
            await session.refresh(room)
            # Register MAS with CFN mgmt plane so coordination can use CFN mode
            if not room.mas_id:
                await _sync_create_mas(room, session)
    return room


def _coord_short_id_from_display(name: str) -> str | None:
    """Extract the short_id from a session-shadow display name."""
    if ":session:" not in name:
        return None
    return name.split(":session:", 1)[1]


async def _resolve_coord_session(target_room: Room, db: AsyncSession) -> CoordinationSession | None:
    """Find the CoordinationSession for an existing session-shadow Room row."""
    if target_room.is_namespace or not target_room.parent_namespace:
        return None
    short_id = _coord_short_id_from_display(target_room.name)
    if not short_id:
        return None
    result = await db.execute(
        select(CoordinationSession).where(
            CoordinationSession.parent_room_name == target_room.parent_namespace,
            CoordinationSession.short_id == short_id,
        )
    )
    return result.scalar_one_or_none()


async def _spawn_session_room(
    parent_name: str, db: AsyncSession
) -> tuple[Room, CoordinationSession]:
    """Create an ephemeral sync session room + CoordinationSession entity.

    If there's already a pending session (idle/waiting) in this namespace,
    return it instead of creating a new one.
    """
    # Check for existing pending session-shadow in this namespace
    result = await db.execute(
        select(Room).where(
            Room.parent_namespace == parent_name,
            Room.coordination_state.in_(["idle", "waiting", "negotiating"]),
        )
    )
    existing_room = result.scalar_one_or_none()
    if existing_room:
        existing_coord = await _resolve_coord_session(existing_room, db)
        if existing_coord:
            return existing_room, existing_coord
        # Pre-0011 data without a backfilled coord_session — repair on the fly.
        repair = CoordinationSession(
            parent_room_name=parent_name,
            short_id=_coord_short_id_from_display(existing_room.name) or uuid4().hex[:8],
            state=existing_room.coordination_state or "idle",
            mas_id=existing_room.mas_id,
            workspace_id=existing_room.workspace_id,
        )
        db.add(repair)
        await db.flush()
        return existing_room, repair

    # Create a new session room, inheriting workspace/mas from parent
    short_id = uuid4().hex[:8]
    session_name = f"{parent_name}:session:{short_id}"

    parent_result = await db.execute(select(Room).where(Room.name == parent_name))
    parent_room = parent_result.scalar_one_or_none()

    session_room = Room(
        name=session_name,
        is_public=True,
        mode="sync",
        is_namespace=False,
        parent_namespace=parent_name,
        namespace=parent_name,
        workspace_id=parent_room.workspace_id if parent_room else None,
        mas_id=parent_room.mas_id if parent_room else None,
    )
    db.add(session_room)

    # Dual-write the first-class CoordinationSession entity (#197). The shadow
    # Room row above stays during the deprecation window so messages.room_name
    # FKs keep resolving.
    coord_session = CoordinationSession(
        parent_room_name=parent_name,
        short_id=short_id,
        state="idle",
        mas_id=parent_room.mas_id if parent_room else None,
        workspace_id=parent_room.workspace_id if parent_room else None,
    )
    db.add(coord_session)

    await db.flush()
    await db.refresh(session_room)
    logger.info("Spawned session %s in namespace %s", session_name, parent_name)
    return session_room, coord_session


@router.post("/spawn", response_model=dict, status_code=201)
async def spawn_session(
    room_name: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Explicitly spawn a negotiation session within a namespace room."""
    result = await db.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if not room.is_namespace:
        raise HTTPException(status_code=400, detail="Can only spawn sessions in namespace rooms")

    session_room, _ = await _spawn_session_room(room_name, db)
    await db.commit()

    cfn_enabled = bool(settings.COGNITION_FABRIC_NODE_URL and room.mas_id and room.workspace_id)
    result = {
        "session_room": session_room.name,
        "parent": room_name,
        "cfn": {
            "enabled": cfn_enabled,
            "mas_id": str(room.mas_id) if room.mas_id else None,
            "workspace_id": str(room.workspace_id) if room.workspace_id else None,
        },
    }
    return result


@router.post("", response_model=ParticipantRead, status_code=201)
async def join_room(
    room_name: str,
    payload: ParticipantCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Join a room. If the room is a namespace, auto-spawns a session and joins that."""
    room = await _upsert_room(room_name, db)

    # Resolve the coordination session this join attaches to.
    target_room = room
    coord_session: CoordinationSession | None = None
    if room.is_namespace:
        target_room, coord_session = await _spawn_session_room(room_name, db)
    else:
        coord_session = await _resolve_coord_session(target_room, db)

    if coord_session is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No coordination session found for room {room_name!r}. "
                "Either pass a namespace to auto-spawn, or a session-shadow display name."
            ),
        )

    sess = Participant(
        coordination_session_id=coord_session.id,
        agent_handle=payload.agent_handle,
        intent=payload.intent,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    # Register agent handle in CFN mgmt plane (non-fatal, fire-and-forget)
    asyncio.ensure_future(_register_agent_cfn(room, payload.agent_handle))

    # Post coordination_join notification
    asyncio.ensure_future(_notify_join(target_room.name, payload.agent_handle, payload.intent))

    # Start join timer for sync session rooms
    if not target_room.is_namespace and target_room.coordination_state == "idle":
        deadline = datetime.now(UTC) + timedelta(seconds=settings.COORDINATION_JOIN_WINDOW_SECONDS)
        result = await db.execute(
            update(Room)
            .where(Room.name == target_room.name, Room.coordination_state == "idle")
            .values(coordination_state="waiting", join_deadline=deadline)
            .returning(Room.id)
        )
        claimed = result.scalar_one_or_none()
        await db.commit()

        if claimed is not None:
            from app.services import coordination

            coordination.schedule_join_timer(target_room.name, deadline)
            logger.info(
                "Coordination join timer started for session %s (deadline=%s)",
                target_room.name,
                deadline,
            )
    elif (
        not target_room.is_namespace
        and target_room.coordination_state == "waiting"
        and settings.COORDINATION_JOIN_WINDOW_EXTENSION_SECONDS > 0
    ):
        # Subsequent joiner: extend the window so slow agents get a chance to
        # join too. Cap at COORDINATION_JOIN_WINDOW_MAX_SECONDS measured from
        # the session's first-join time (current join_deadline minus the
        # initial window) to bound the total wait. Same pattern as the
        # round-watchdog extension fix — extend on activity, hard cap.
        from app.services import coordination

        now = datetime.now(UTC)
        current_deadline = target_room.join_deadline
        # SQLite returns offset-naive datetimes from DateTime columns; coerce
        # to UTC-aware before any arithmetic so we don't trip
        # "can't compare offset-naive and offset-aware datetimes" in tests.
        if current_deadline is not None and current_deadline.tzinfo is None:
            current_deadline = current_deadline.replace(tzinfo=UTC)
        first_join_at = (
            current_deadline - timedelta(seconds=settings.COORDINATION_JOIN_WINDOW_SECONDS)
            if current_deadline
            else now
        )
        max_deadline = first_join_at + timedelta(
            seconds=settings.COORDINATION_JOIN_WINDOW_MAX_SECONDS
        )
        proposed = now + timedelta(seconds=settings.COORDINATION_JOIN_WINDOW_EXTENSION_SECONDS)
        new_deadline = min(proposed, max_deadline)
        # Only push forward — never shorten an already-longer deadline.
        if current_deadline is None or new_deadline > current_deadline:
            await db.execute(
                update(Room)
                .where(Room.name == target_room.name, Room.coordination_state == "waiting")
                .values(join_deadline=new_deadline)
            )
            await db.commit()
            coordination.schedule_join_timer(target_room.name, new_deadline)
            logger.info(
                "Coordination join window extended for %s on join by %s (deadline=%s, capped=%s)",
                target_room.name,
                payload.agent_handle,
                new_deadline,
                new_deadline >= max_deadline,
            )

    return sess


async def _register_agent_cfn(room: Room, handle: str) -> None:
    """Register an agent handle in the CFN mgmt plane MAS. Non-fatal."""
    import time

    from app.services.metrics import record_cfn_call

    if not settings.CFN_MGMT_URL or not room.mas_id or not room.workspace_id:
        return
    t0 = time.monotonic()
    try:
        url = f"{settings.CFN_MGMT_URL}/api/workspaces/{room.workspace_id}/cognitive-agents"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"cognitive_agent_name": handle})
        # 409 here means "this cognitive agent is already registered in
        # the MAS" — entirely benign, since `_register_agent_cfn` is fire-
        # and-forget on every `session join` and the same handle (e.g.
        # alpha/beta in distributed E2E) joins many sessions per workspace.
        # Treat it the same as `register_memory_provider` does in
        # main.py:103 to avoid skewing the CFN Transport Health error
        # rate (we've seen 80/80 mgmt errors all turn out to be 409s).
        record_cfn_call(
            service="mgmt",
            operation="register_agent",
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=resp.status_code,
            error=resp.status_code >= 400 and resp.status_code != 409,
        )
        if resp.status_code == 409:
            logger.debug(
                "CFN agent %s already registered in workspace %s",
                handle,
                room.workspace_id,
            )
        else:
            logger.debug(
                "CFN agent registered: %s in workspace %s",
                handle,
                room.workspace_id,
            )
    except Exception as exc:
        record_cfn_call(
            service="mgmt",
            operation="register_agent",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        logger.warning("CFN register agent failed for %s: %s", handle, exc)


async def _notify_join(room_name: str, handle: str, intent: str | None) -> None:
    """Fire NOTIFY for coordination_join so SSE consumers see it immediately."""
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
                    "room_name": room_name,
                    "sender_handle": "CognitiveEngine",
                    "message_type": "coordination_join",
                    "content": json.dumps({"handle": handle, "intent": intent}),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("NOTIFY coordination_join failed: %s", e)


@router.get("/coordination", response_model=list[CoordinationSessionRead])
async def list_coordination_sessions(
    room_name: str,
    db: AsyncSession = Depends(get_async_session),
):
    """List negotiation sessions in a room (#197).

    Returns first-class CoordinationSession entities. The shadow rows in the
    rooms table are an implementation detail that callers shouldn't depend on.
    """
    parent = (await db.execute(select(Room).where(Room.name == room_name))).scalar_one_or_none()
    if not parent:
        raise HTTPException(status_code=404, detail="Room not found")

    result = await db.execute(
        select(CoordinationSession)
        .where(CoordinationSession.parent_room_name == room_name)
        .order_by(CoordinationSession.created_at.desc())
    )
    return [CoordinationSessionRead.model_validate(s) for s in result.scalars().all()]


@router.get("", response_model=ParticipantListResponse)
async def list_sessions(
    room_name: str,
    db: AsyncSession = Depends(get_async_session),
):
    """List agents participating in a room's coordination session."""
    room = (await db.execute(select(Room).where(Room.name == room_name))).scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Resolve which coord_session(s) this room corresponds to. For a namespace,
    # gather all participants across all its coord_sessions; for a session
    # shadow, just that one.
    if room.is_namespace:
        coord_q = select(CoordinationSession.id).where(
            CoordinationSession.parent_room_name == room_name
        )
    else:
        coord = await _resolve_coord_session(room, db)
        if coord is None:
            return ParticipantListResponse(participants=[], total=0)
        coord_q = select(CoordinationSession.id).where(CoordinationSession.id == coord.id)

    result = await db.execute(
        select(Participant)
        .where(Participant.coordination_session_id.in_(coord_q))
        .order_by(Participant.joined_at.desc())
    )
    participants = list(result.scalars().all())

    return ParticipantListResponse(
        participants=[ParticipantRead.model_validate(p) for p in participants],
        total=len(participants),
    )


@router.delete("/{session_id}", status_code=204)
async def leave_room(
    room_name: str,
    session_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove a participant (agent leaves the session)."""
    result = await db.execute(select(Participant).where(Participant.id == session_id))
    participant = result.scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")

    await db.delete(participant)
    await db.commit()
