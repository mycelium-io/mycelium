"""
Multi-agent coordination service.

Manages the join-window → tick-based negotiation lifecycle for Mycelium rooms.
State is in-memory (v1) — cleared on server restart.

Flow:
  1. First agent joins → start 60s join timer
  2. Timer fires → tick 0: collect intents, run SemanticNegotiationPipeline,
     post coordination_tick per SAO round via RoomNegotiator
  3. Agents respond → on_agent_response routes replies to the correct RoomNegotiator
  4. NegMAS mechanism produces agreement → post coordination_consensus
  5. Mark room complete
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

import asyncpg
from sqlalchemy import select, update

from app.agents.semantic_negotiation import (
    NegotiationParticipant,
    SemanticNegotiationPipeline,
)
from app.bus import agent_channel, notify, room_channel
from app.config import settings
from app.database import async_session_maker
from app.models import Message, Room, Session

logger = logging.getLogger(__name__)

# In-memory per-room tick state
# {room_name: {tick, responses, expected, tick_timeout_task}}
_state: dict[str, dict] = {}

# Per-room lock to prevent duplicate _run_tick calls
_locks: dict[str, asyncio.Lock] = {}

# Active SemanticNegotiationPipeline per room (set after tick-0 launch)
# Keyed by room_name; the pipeline exposes .negotiator_registry {participant_id: RoomNegotiator}
_pipelines: dict[str, SemanticNegotiationPipeline] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def start_join_timer(room_name: str, deadline: datetime) -> None:
    """Sleep until join window closes, then run tick 0."""
    sleep_secs = (deadline - _utcnow()).total_seconds()
    if sleep_secs > 0:
        await asyncio.sleep(sleep_secs)
    await _run_tick(room_name, tick=0)


async def _run_tick(room_name: str, tick: int) -> None:
    """Tick 0: launch the SemanticNegotiationPipeline in a background thread.
    Subsequent ticks are driven by on_agent_response → RoomNegotiator.on_agent_reply."""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Session)
            .where(Session.room_name == room_name)
            .order_by(Session.joined_at)
        )
        sessions = list(result.scalars().all())

        if not sessions:
            logger.warning("No sessions found for room %s at tick %d", room_name, tick)
            return

        session_handles = [s.agent_handle for s in sessions]
        intents = [s.intent or "" for s in sessions]

        await db.execute(
            update(Room)
            .where(Room.name == room_name)
            .values(coordination_state="negotiating")
        )
        await db.commit()

    if tick != 0:
        # Subsequent ticks are handled by on_agent_response routing to the pipeline
        return

    # --- Tick 0: initialise state and launch pipeline ---
    _state[room_name] = {
        "tick": 0,
        "responses": {},
        "expected": len(sessions),
        "tick_timeout_task": None,
    }

    await _post_message(
        room_name,
        message_type="coordination_start",
        content=json.dumps({"round": 0, "agent_count": len(sessions)}),
    )

    participants = [
        NegotiationParticipant(id=handle, name=handle)
        for handle in session_handles
    ]
    joined_intents = "\n".join(f"- {handle}: {intent}" for handle, intent in zip(session_handles, intents))

    loop = asyncio.get_event_loop()
    pipeline = SemanticNegotiationPipeline(
        participants=participants,
        room_name=room_name,
        loop=loop,
        post_message_coro=_post_message,
        reply_timeout=float(settings.COORDINATION_TICK_TIMEOUT_SECONDS),
    )
    _pipelines[room_name] = pipeline

    # Run the blocking NegMAS mechanism in a thread so it doesn't stall the loop.
    # The mechanism drives RoomNegotiators which post coordination_tick messages
    # and block waiting for agent replies routed back via on_agent_response.
    async def _run_pipeline() -> None:
        try:
            result = await asyncio.to_thread(pipeline.run, content_text=joined_intents)
            if result.agreement:
                assignments = {o.issue_id: o.chosen_option for o in result.agreement}
                plan = "; ".join(f"{k}={v}" for k, v in assignments.items())
            else:
                assignments = {}
                plan = "No agreement reached"
            await _post_message(
                room_name,
                message_type="coordination_consensus",
                content=json.dumps({
                    "round": result.steps,
                    "plan": plan,
                    "assignments": assignments,
                    "timedout": result.timedout,
                    "broken": result.broken,
                }),
            )
            async with async_session_maker() as db:
                await db.execute(
                    update(Room)
                    .where(Room.name == room_name)
                    .values(coordination_state="complete")
                )
                await db.commit()
        except Exception as exc:
            logger.error("Negotiation pipeline failed for room %s: %s", room_name, exc)
        finally:
            _state.pop(room_name, None)
            _pipelines.pop(room_name, None)

    asyncio.ensure_future(_run_pipeline())


async def on_agent_response(room_name: str, handle: str, content: str) -> None:
    """Called by messages route when an agent posts in a negotiating room.

    Routes the reply to the matching RoomNegotiator (keyed by agent handle /
    participant_id) so the pending SAO round future is resolved.
    """
    # Route to the active pipeline's negotiator registry
    pipeline = _pipelines.get(room_name)
    if pipeline is not None:
        registry = getattr(pipeline, "negotiator_registry", {})
        negotiator = registry.get(handle)
        if negotiator is not None:
            logger.debug("Room %s: routing reply from %s to RoomNegotiator", room_name, handle)
            negotiator.on_agent_reply(content)
            return

    # Fallback: legacy tick-based state tracking (no pipeline active)
    state = _state.get(room_name)
    if not state:
        return

    if room_name not in _locks:
        _locks[room_name] = asyncio.Lock()
    lock = _locks[room_name]

    should_advance = False
    next_tick = 0

    async with lock:
        state["responses"][handle] = content
        logger.debug(
            "Room %s: %d/%d responses for tick %d",
            room_name,
            len(state["responses"]),
            state.get("expected", "?"),
            state.get("tick", "?"),
        )

        if len(state["responses"]) >= state.get("expected", 999):
            task = state.get("tick_timeout_task")
            if task and not task.done():
                task.cancel()
            next_tick = state["tick"] + 1
            should_advance = True

    if should_advance:
        await _run_tick(room_name, next_tick)


async def _post_message(room_name: str, message_type: str, content: str) -> None:
    """Insert a coordination message to DB and notify SSE subscribers."""
    async with async_session_maker() as db:
        msg = Message(
            room_name=room_name,
            sender_handle="CognitiveEngine",
            message_type=message_type,
            content=content,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        msg_id = str(msg.id)
        created_at = msg.created_at.isoformat()

    # Determine which agent handles to notify directly
    agent_handles: list[str] = []
    if message_type == "coordination_tick":
        try:
            parsed = json.loads(content)
            agent_handles = parsed.get("addressed_to") or []
            if not agent_handles and parsed.get("participant_id"):
                agent_handles = [parsed["participant_id"]]
        except Exception:
            pass
    elif message_type == "coordination_consensus":
        async with async_session_maker() as db:
            result = await db.execute(
                select(Session.agent_handle).where(Session.room_name == room_name)
            )
            agent_handles = list(result.scalars().all())

    try:
        parsed = urlparse(settings.DATABASE_URL)
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
        payload = {
            "id": msg_id,
            "room_name": room_name,
            "sender_handle": "CognitiveEngine",
            "message_type": message_type,
            "content": content,
            "created_at": created_at,
        }
        try:
            await notify(conn, room_channel(room_name), payload)
            for handle in agent_handles:
                await notify(conn, agent_channel(handle), payload)
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("NOTIFY failed for room %s: %s", room_name, e)


