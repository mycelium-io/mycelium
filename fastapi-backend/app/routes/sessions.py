"""
Sessions API — tracks agent presence in rooms.

POST   /rooms/{room}/sessions       — join a room (creates room if needed, starts coordination timer)
GET    /rooms/{room}/sessions       — list who is in a room
DELETE /rooms/{room}/sessions/{id}  — leave a room
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import notify, room_channel
from app.config import settings
from app.database import get_async_session
from app.models import Room, Session
from app.schemas import SessionCreate, SessionListResponse, SessionRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/sessions", tags=["sessions"])


async def _upsert_room(room_name: str, session: AsyncSession) -> Room:
    """Get existing room or create it (for coordination auto-join)."""
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        room = Room(name=room_name, is_public=True)
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
    return room


@router.post("", response_model=SessionRead, status_code=201)
async def join_room(
    room_name: str,
    payload: SessionCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Register agent presence in a room (join). Creates room if it doesn't exist."""
    room = await _upsert_room(room_name, db)

    sess = Session(
        room_name=room_name,
        agent_handle=payload.agent_handle,
        intent=payload.intent,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    # Post coordination_join notification (fire-and-forget via NOTIFY)
    asyncio.ensure_future(
        _notify_join(room_name, payload.agent_handle, payload.intent)
    )

    # Start join timer when first agent arrives — use conditional UPDATE to avoid duplicates
    if room.coordination_state == "idle":
        deadline = datetime.now(UTC) + timedelta(
            seconds=settings.COORDINATION_JOIN_WINDOW_SECONDS
        )
        result = await db.execute(
            update(Room)
            .where(Room.name == room_name, Room.coordination_state == "idle")
            .values(coordination_state="waiting", join_deadline=deadline)
            .returning(Room.id)
        )
        claimed = result.scalar_one_or_none()
        await db.commit()

        if claimed is not None:
            # We won the race — schedule the timer
            from app.services import coordination
            asyncio.ensure_future(coordination.start_join_timer(room_name, deadline))
            logger.info(
                "Coordination join timer started for room %s (deadline=%s)", room_name, deadline
            )

    return sess


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


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    room_name: str,
    db: AsyncSession = Depends(get_async_session),
):
    """List agents currently in a room."""
    result = await db.execute(select(Room).where(Room.name == room_name))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Room not found")

    result = await db.execute(
        select(Session)
        .where(Session.room_name == room_name)
        .order_by(Session.joined_at.desc())
    )
    sessions = list(result.scalars().all())

    return SessionListResponse(
        sessions=[SessionRead.model_validate(s) for s in sessions],
        total=len(sessions),
    )


@router.delete("/{session_id}", status_code=204)
async def leave_room(
    room_name: str,
    session_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove an agent session (leave room)."""
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.room_name == room_name,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    await db.commit()
