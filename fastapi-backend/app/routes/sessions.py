# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

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
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import notify, room_channel
from app.config import settings
from app.database import get_async_session
from app.models import AuditEvent, CoordinationSession, Message, Participant, Room
from app.routes.rooms import _sync_create_mas
from app.schemas import (
    ContextFile,
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


async def _resolve_coord_session_by_display(
    display_name: str, db: AsyncSession
) -> CoordinationSession | None:
    """Resolve a ``{parent}:session:{short}`` string to its CoordinationSession."""
    if ":session:" not in display_name:
        return None
    parent, _, short_id = display_name.partition(":session:")
    if not parent or not short_id:
        return None
    result = await db.execute(
        select(CoordinationSession).where(
            CoordinationSession.parent_room_name == parent,
            CoordinationSession.short_id == short_id,
        )
    )
    return result.scalar_one_or_none()


async def _spawn_coordination_session(parent_name: str, db: AsyncSession) -> CoordinationSession:
    """Create or return a pending CoordinationSession in a namespace.

    Sessions live exclusively in ``coordination_sessions`` — there is no
    backing row in ``rooms``. Display names are synthesized from
    ``parent_room_name + ":session:" + short_id`` so the SSE and messages
    URLs that address sessions by name keep working.

    Concurrency: on Postgres we hold a transaction-scoped advisory lock keyed
    by ``parent_name`` for the duration of the SELECT-then-INSERT, so two
    concurrent joins for the same room serialize through here and exactly
    one INSERT wins (#280). The partial unique index on
    ``coordination_sessions(parent_room_name) WHERE state IN
    ('idle','waiting','negotiating')`` is the defense-in-depth backstop: even
    if the lock is bypassed somehow, the second INSERT fails with
    IntegrityError and we re-fetch the winning row.
    """
    if db.bind and db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"coord_session_spawn:{parent_name}"},
        )

    result = await db.execute(
        select(CoordinationSession)
        .where(
            CoordinationSession.parent_room_name == parent_name,
            CoordinationSession.state.in_(["idle", "waiting", "negotiating"]),
        )
        .order_by(CoordinationSession.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    parent_result = await db.execute(select(Room).where(Room.name == parent_name))
    parent_room = parent_result.scalar_one_or_none()

    coord = CoordinationSession(
        parent_room_name=parent_name,
        short_id=uuid4().hex[:8],
        state="idle",
        mas_id=parent_room.mas_id if parent_room else None,
        workspace_id=parent_room.workspace_id if parent_room else None,
    )
    db.add(coord)
    try:
        await db.flush()
    except IntegrityError:
        # Lock bypassed (no PG, or pre-existing migration race): re-fetch.
        await db.rollback()
        result = await db.execute(
            select(CoordinationSession)
            .where(
                CoordinationSession.parent_room_name == parent_name,
                CoordinationSession.state.in_(["idle", "waiting", "negotiating"]),
            )
            .order_by(CoordinationSession.created_at.desc())
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise
        logger.info(
            "Coordination session spawn lost the unique-index race for %s; "
            "returning the winner (%s)",
            parent_name,
            existing.id,
        )
        return existing
    logger.info("Spawned coordination session %s in namespace %s", coord.id, parent_name)
    return coord


@router.post("/spawn", response_model=dict, status_code=201)
async def spawn_session(
    room_name: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Explicitly spawn a negotiation session within a room."""
    result = await db.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    coord = await _spawn_coordination_session(room_name, db)
    await db.commit()

    cfn_enabled = bool(settings.CFN_SVC_URL and room.mas_id and room.workspace_id)
    return {
        "session_room": coord.display_name,
        "coordination_session_id": str(coord.id),
        "parent": room_name,
        "cfn": {
            "enabled": cfn_enabled,
            "mas_id": str(room.mas_id) if room.mas_id else None,
            "workspace_id": str(room.workspace_id) if room.workspace_id else None,
        },
    }


@router.post("", response_model=ParticipantRead, status_code=201)
async def join_room(
    room_name: str,
    payload: ParticipantCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Join a room. Auto-spawns a coordination session if one doesn't exist."""
    room = await _upsert_room(room_name, db)

    # Auto-spawn or fetch the active coordination session for this room.
    coord_session = await _spawn_coordination_session(room_name, db)

    context_files_payload = (
        [cf.model_dump() for cf in payload.context_files] if payload.context_files else None
    )
    # Idempotent on (coordination_session_id, agent_handle): if the harness/CLI
    # AND the agent itself both call ``mycelium session join`` for the same
    # handle (per SKILL.md), the second call must NOT double-count (#284).
    #
    # Fast path: SELECT for an existing participant first; if found, return it
    # without touching state. The partial unique index is the backstop for the
    # true-concurrent case (two POSTs racing past the SELECT) — we catch the
    # IntegrityError there with begin_nested so the outer transaction stays
    # usable for the join-window state machine that runs below.
    existing_q = await db.execute(
        select(Participant).where(
            Participant.coordination_session_id == coord_session.id,
            Participant.agent_handle == payload.agent_handle,
        )
    )
    existing_sess = existing_q.scalar_one_or_none()
    duplicate_join = False
    if existing_sess is not None:
        duplicate_join = True
        sess: Participant = existing_sess
        logger.info(
            "Duplicate join for handle=%s session=%s; returning existing participant %s",
            payload.agent_handle,
            coord_session.id,
            sess.id,
        )
    else:
        sess = Participant(
            coordination_session_id=coord_session.id,
            agent_handle=payload.agent_handle,
            intent=payload.intent,
            context_files=context_files_payload,
        )
        db.add(sess)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            # Concurrent join slipped through the SELECT — the unique index
            # caught us. Re-fetch the winner and downgrade to a duplicate join.
            duplicate_join = True
            existing_q = await db.execute(
                select(Participant).where(
                    Participant.coordination_session_id == coord_session.id,
                    Participant.agent_handle == payload.agent_handle,
                )
            )
            sess = existing_q.scalar_one()
            logger.info(
                "Concurrent join for handle=%s session=%s lost the unique-index race; "
                "returning the winner (%s)",
                payload.agent_handle,
                coord_session.id,
                sess.id,
            )
        await db.commit()
    await db.refresh(sess)

    # Register agent handle in CFN mgmt plane (non-fatal, fire-and-forget).
    # Already idempotent on duplicates — 409 is treated as benign — so fire
    # this on dup joins too.
    asyncio.ensure_future(_register_agent_cfn(room, payload.agent_handle))

    # The remaining side effects (context-files audit + fan-in, the
    # coordination_join notification, and the join-window state machine)
    # MUST run exactly once per real join. A duplicate call from the same
    # handle re-enters this endpoint but should be a no-op past this point —
    # otherwise we double-post coordination_join, re-fan context files into
    # KXP, and bump the join-window deadline twice.
    if duplicate_join:
        return sess

    # Audit + KXP fan-in for opt-in shared context files. The agent
    # deliberately selected these via --context-files; treat them as room
    # writes, mirroring channel_message / memory_set in Part 1.
    if payload.context_files:
        await _record_context_files_audit(db, room, payload.agent_handle, payload.context_files)
        from app.services.knowledge_fanin import fan_in

        for cf in payload.context_files:
            asyncio.ensure_future(
                fan_in(
                    room_name=room_name,
                    sender_handle=payload.agent_handle,
                    content=cf.content,
                    source="context_file",
                )
            )

    # Persist the join as Message rows so the agent's opening position
    # (``intent``) is auditable post-hoc — catchup readers (``GET
    # /rooms/<r>/messages``, the frontend on first load) only ever see
    # what's in the message log, not transient SSE NOTIFY payloads. Without
    # this row a later observer can't tell what positions the agents
    # brought into the negotiation.
    #
    # We write TWO rows on purpose: one session-scoped (visible in the
    # session EVENT LOG via the coord-session messages endpoint) and one
    # room-scoped (visible in the parent room's EVENTS tab via the
    # standard rooms-messages endpoint). The Message table's
    # ``ck_messages_one_target`` CHECK enforces room_name XOR
    # coordination_session_id — they cannot be combined in one row — so the
    # dual-post is the right way to make a join visible at both levels.
    # Cascade is fine: each row dies with its respective parent.
    # ``session`` (display_name) is included so the frontend can link from the
    # chat-channel rendering of the join out to the live session view — the
    # room-scoped row has ``coordination_session_id=None`` so the link target
    # can't be derived from the row alone.
    join_content = json.dumps(
        {
            "handle": payload.agent_handle,
            "intent": payload.intent,
            "session": coord_session.display_name,
        }
    )
    db.add(
        Message(
            room_name=None,
            coordination_session_id=coord_session.id,
            sender_handle="CognitiveEngine",
            message_type="coordination_join",
            content=join_content,
        )
    )
    db.add(
        Message(
            room_name=coord_session.parent_room_name,
            coordination_session_id=None,
            sender_handle="CognitiveEngine",
            message_type="coordination_join",
            content=join_content,
        )
    )
    await db.commit()

    # Fire the live NOTIFY for subscribers connected right now.
    asyncio.ensure_future(
        _notify_join(coord_session.display_name, payload.agent_handle, payload.intent)
    )

    # Drive the join-window state machine on the CoordinationSession.
    if coord_session.state == "idle":
        deadline = datetime.now(UTC) + timedelta(seconds=settings.COORDINATION_JOIN_WINDOW_SECONDS)
        result = await db.execute(
            update(CoordinationSession)
            .where(
                CoordinationSession.id == coord_session.id,
                CoordinationSession.state == "idle",
            )
            .values(state="waiting", join_window_ends_at=deadline)
            .returning(CoordinationSession.id)
        )
        claimed = result.scalar_one_or_none()
        await db.commit()

        if claimed is not None:
            from app.services import coordination

            coordination.schedule_join_timer(coord_session.display_name, deadline)
            logger.info(
                "Coordination join timer started for session %s (deadline=%s)",
                coord_session.display_name,
                deadline,
            )
    elif (
        coord_session.state == "waiting" and settings.COORDINATION_JOIN_WINDOW_EXTENSION_SECONDS > 0
    ):
        from app.services import coordination

        now = datetime.now(UTC)
        current_deadline = coord_session.join_window_ends_at
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
        if current_deadline is None or new_deadline > current_deadline:
            await db.execute(
                update(CoordinationSession)
                .where(
                    CoordinationSession.id == coord_session.id,
                    CoordinationSession.state == "waiting",
                )
                .values(join_window_ends_at=new_deadline)
            )
            await db.commit()
            coordination.schedule_join_timer(coord_session.display_name, new_deadline)
            logger.info(
                "Coordination join window extended for %s on join by %s (deadline=%s, capped=%s)",
                coord_session.display_name,
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


async def _record_context_files_audit(
    db: AsyncSession,
    room: Room,
    handle: str,
    files: list[ContextFile],
) -> None:
    """Write a durable record of which files an agent opted into sharing.

    Stores ``path`` and ``sha256`` only — content lives on the participant
    row and (via fan-in) in KXP. The audit row captures consent: who shared
    what, in which room, identified by hash.
    """
    nil_uuid = UUID(int=0)
    now = datetime.now(UTC)
    db.add(
        AuditEvent(
            resource_type="MAS",
            resource_identifier=str(room.mas_id) if room.mas_id else room.name,
            audit_type="KNOWLEDGE_INGESTION",
            audit_resource_identifier=handle,
            audit_information={
                "kind": "context_files_shared",
                "room": room.name,
                "files": [{"path": cf.path, "sha256": cf.sha256} for cf in files],
            },
            created_by=nil_uuid,
            created_on=now,
            last_modified_by=nil_uuid,
            last_modified_on=now,
        )
    )
    await db.commit()


@router.get("/coordination", response_model=list[CoordinationSessionRead])
async def list_coordination_sessions(
    room_name: str,
    db: AsyncSession = Depends(get_async_session),
):
    """List negotiation sessions in a room.

    Returns first-class CoordinationSession entities scoped to ``room_name``.
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
    """List agents participating in a room's coordination session(s).

    Accepts either a real room name (returns participants across all its
    coord_sessions) or a legacy ``{parent}:session:{short}`` display name
    (returns participants of just that one session).
    """
    coord = await _resolve_coord_session_by_display(room_name, db)
    if coord is not None:
        coord_q = select(CoordinationSession.id).where(CoordinationSession.id == coord.id)
    else:
        room = (await db.execute(select(Room).where(Room.name == room_name))).scalar_one_or_none()
        if not room:
            raise HTTPException(status_code=404, detail="Room or session not found")
        coord_q = select(CoordinationSession.id).where(
            CoordinationSession.parent_room_name == room_name
        )

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
    result = await db.execute(
        select(Participant)
        .join(CoordinationSession, Participant.coordination_session_id == CoordinationSession.id)
        .where(Participant.id == session_id, CoordinationSession.parent_room_name == room_name)
    )
    participant = result.scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")

    await db.delete(participant)
    await db.commit()
