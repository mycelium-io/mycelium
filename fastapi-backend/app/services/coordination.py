# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Multi-agent coordination service.

Manages the join-window → tick-based negotiation lifecycle for Mycelium rooms.
State is in-memory (v1) — cleared on server restart.

Two coordination modes:

  CFN mode (when COGNITION_FABRIC_NODE_URL + room.mas_id are set):
    1. First agent joins → start join timer
    2. Timer fires → call CFN start, fan out coordination_ticks to ALL agents at once
    3. Agents reply → replies collected in _cfn_state[room_name].pending_replies
    4. Once ALL agents reply → call CFN decide
    5. CFN returns "ongoing" → fan out next round; "agreed" → post coordination_consensus
    6. Repeat until agreed or max steps exhausted

  Inline NegMAS mode (fallback when CFN not configured):
    1. First agent joins → start 60s join timer
    2. Timer fires → tick 0: run SemanticNegotiationPipeline (NegMAS SAO),
       post coordination_tick per SAO round via RoomNegotiator (one agent at a time)
    3. Agents respond → on_agent_response routes replies to the correct RoomNegotiator
    4. NegMAS mechanism produces agreement → post coordination_consensus
    5. Mark room complete
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

import asyncpg
from sqlalchemy import select, update

from app.agents.semantic_negotiation import (
    NegotiationParticipant,
    SemanticNegotiationPipeline,
)
from app.bus import agent_channel, notify, room_channel
from app.config import require_llm, settings
from app.database import async_session_maker
from app.models import Message, Room, Session

logger = logging.getLogger(__name__)

# In-memory per-room tick state (inline NegMAS mode)
# {room_name: {tick, responses, expected, tick_timeout_task}}
_state: dict[str, dict] = {}

# Per-room lock to prevent duplicate _run_tick calls
_locks: dict[str, asyncio.Lock] = {}

# Active SemanticNegotiationPipeline per room (set after tick-0 launch)
# Keyed by room_name; the pipeline exposes .negotiator_registry {participant_id: RoomNegotiator}
_pipelines: dict[str, SemanticNegotiationPipeline] = {}


# ── CFN mode state ─────────────────────────────────────────────────────────────


@dataclass
class _CfnRoundState:
    session_id: str
    workspace_id: str
    mas_id: str
    agents: list[str]  # agent handles expected each round
    pending_replies: dict[str, dict | None] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# {room_name: _CfnRoundState}
_cfn_state: dict[str, _CfnRoundState] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def start_join_timer(room_name: str, deadline: datetime) -> None:
    """Sleep until join window closes, then run tick 0."""
    sleep_secs = (deadline - _utcnow()).total_seconds()
    if sleep_secs > 0:
        await asyncio.sleep(sleep_secs)
    await _run_tick(room_name, tick=0)


async def _run_tick(room_name: str, tick: int) -> None:
    """Tick 0: launch negotiation. Mode selected by config + room.mas_id."""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Session).where(Session.room_name == room_name).order_by(Session.joined_at)
        )
        sessions = list(result.scalars().all())

        if not sessions:
            logger.warning("No sessions found for room %s at tick %d", room_name, tick)
            return

        session_handles = [s.agent_handle for s in sessions]
        intents = [s.intent or "" for s in sessions]

        # Load room — mas_id lives on the namespace room, not the session room
        room_result = await db.execute(select(Room).where(Room.name == room_name))
        room = room_result.scalar_one_or_none()
        if room is not None and room.mas_id is None and room.parent_namespace:
            ns_result = await db.execute(select(Room).where(Room.name == room.parent_namespace))
            ns_room = ns_result.scalar_one_or_none()
            if ns_room is not None and ns_room.mas_id:
                room = ns_room

        await db.execute(
            update(Room).where(Room.name == room_name).values(coordination_state="negotiating")
        )
        await db.commit()

    if tick != 0:
        # Subsequent ticks are handled by on_agent_response routing to the pipeline
        return

    # Decide mode: CFN or inline NegMAS
    use_cfn = bool(
        settings.COGNITION_FABRIC_NODE_URL
        and room is not None
        and room.mas_id
        and room.workspace_id
    )

    if use_cfn:
        await _run_cfn_negotiation(room_name, room, session_handles, intents)
    else:
        await _run_negmas_negotiation(room_name, session_handles, intents)


async def _run_cfn_negotiation(
    room_name: str,
    room: Room,
    session_handles: list[str],
    intents: list[str],
) -> None:
    """CFN mode: call start, fan out ticks to ALL agents, collect all replies, call decide."""
    from app.services.cfn_negotiation import start_negotiation

    joined_intents = "\n".join(
        f"- {handle}: {intent}" for handle, intent in zip(session_handles, intents, strict=False)
    )
    agents = [{"id": h, "name": h} for h in session_handles]
    session_id = room.mas_id  # use mas_id as the CFN session_id

    await _post_message(
        room_name,
        message_type="coordination_start",
        content=json.dumps({"round": 0, "agent_count": len(session_handles)}),
    )

    result = await start_negotiation(
        session_id=session_id,
        content_text=joined_intents,
        agents=agents,
        workspace_id=room.workspace_id,
        mas_id=room.mas_id,
    )

    if not result:
        logger.error(
            "CFN start_negotiation returned empty result for %s — falling back to NegMAS", room_name
        )
        await _run_negmas_negotiation(room_name, session_handles, intents)
        return

    # Set up CFN round state
    state = _CfnRoundState(
        session_id=session_id,
        workspace_id=room.workspace_id,
        mas_id=room.mas_id,
        agents=session_handles[:],
        pending_replies={h: None for h in session_handles},
    )
    _cfn_state[room_name] = state

    # Fan out coordination_ticks to all agents from the CFN response
    await _fan_out_cfn_messages(room_name, result.get("messages", []))


async def _fan_out_cfn_messages(room_name: str, messages: list[dict]) -> None:
    """Post coordination_tick for each agent listed in CFN messages."""
    for msg in messages:
        payload = msg.get("payload", msg)
        participant_id = payload.get("participant_id")
        if not participant_id:
            continue
        await _post_message(
            room_name,
            message_type="coordination_tick",
            content=json.dumps(
                {
                    "payload": {
                        "participant_id": participant_id,
                        "round": payload.get("round"),
                        "action": payload.get("action"),
                        "allowed_actions": payload.get("allowed_actions", []),
                        "can_counter_offer": payload.get("can_counter_offer", False),
                        "current_offer": payload.get("current_offer"),
                        "proposer_id": payload.get("proposer_id"),
                        "issue_options": payload.get("options_per_issue"),
                        "issues": payload.get("issues"),
                    }
                }
            ),
        )


async def _cfn_decide_round(room_name: str) -> None:
    """Called when all expected agents have replied. Calls CFN decide and processes response."""
    from app.services.cfn_negotiation import decide_negotiation

    state = _cfn_state.get(room_name)
    if not state:
        return

    agent_replies = []
    for handle, reply_data in state.pending_replies.items():
        if reply_data is None:
            # Agent timed out / no structured reply — default to reject
            agent_replies.append({"agent_id": handle, "action": "reject"})
        else:
            agent_replies.append(reply_data)

    result = await decide_negotiation(
        session_id=state.session_id,
        agent_replies=agent_replies,
        workspace_id=state.workspace_id,
        mas_id=state.mas_id,
    )

    if not result:
        logger.error(
            "CFN decide returned empty result for %s — posting failed consensus", room_name
        )
        await _finish_cfn(room_name, plan="CFN decide failed", assignments={}, broken=True)
        return

    # CFN returns a nested envelope: status lives in result["payload"]["status"]
    # and the agreement in result["semantic_context"]["final_agreement"].
    # Fall back to top-level keys for backward compatibility.
    payload = result.get("payload", {})
    status = payload.get("status", result.get("status", ""))

    if status == "agreed":
        final_agreement = (
            result.get("semantic_context", {}).get("final_agreement")
            or result.get("agreement")
            or result.get("assignments")
            or []
        )
        if isinstance(final_agreement, list):
            agreement = {
                item["issue_id"]: item.get("chosen_option", "")
                for item in final_agreement
                if isinstance(item, dict) and "issue_id" in item
            }
        elif isinstance(final_agreement, dict):
            agreement = final_agreement
        else:
            agreement = {}
        plan = (
            "; ".join(f"{k}={v}" for k, v in agreement.items())
            if agreement
            else str(final_agreement)
        )
        await _finish_cfn(room_name, plan=plan, assignments=agreement, broken=False)

    elif status in ("ongoing", "initiated"):
        # Reset replies for next round and fan out new messages
        async with state.lock:
            state.pending_replies = {h: None for h in state.agents}
        messages = payload.get("messages", result.get("messages", []))
        await _fan_out_cfn_messages(room_name, messages)

    else:
        # Unknown / failed status
        logger.warning("CFN decide returned status=%s for %s", status, room_name)
        await _finish_cfn(
            room_name, plan=f"Negotiation ended: {status}", assignments={}, broken=True
        )


async def _finish_cfn(room_name: str, plan: str, assignments: dict, broken: bool) -> None:
    """Post consensus and clean up CFN state."""
    _cfn_state.pop(room_name, None)
    await _post_message(
        room_name,
        message_type="coordination_consensus",
        content=json.dumps(
            {
                "plan": plan,
                "assignments": assignments,
                "broken": broken,
            }
        ),
    )
    async with async_session_maker() as db:
        await db.execute(
            update(Room)
            .where(Room.name == room_name)
            .values(coordination_state="complete" if not broken else "failed")
        )
        await db.commit()


async def _run_negmas_negotiation(
    room_name: str, session_handles: list[str], intents: list[str]
) -> None:
    """Inline NegMAS mode — original implementation."""
    # Check LLM availability before starting negotiation
    try:
        require_llm()
    except RuntimeError as exc:
        logger.error("Cannot start negotiation for %s: %s", room_name, exc)
        await _post_message(
            room_name,
            message_type="coordination_error",
            content=json.dumps({"error": str(exc)}),
        )
        async with async_session_maker() as db:
            await db.execute(
                update(Room).where(Room.name == room_name).values(coordination_state="failed")
            )
            await db.commit()
        return

    # --- Tick 0: initialise state and launch pipeline ---
    _state[room_name] = {
        "tick": 0,
        "responses": {},
        "expected": len(session_handles),
        "tick_timeout_task": None,
    }

    await _post_message(
        room_name,
        message_type="coordination_start",
        content=json.dumps({"round": 0, "agent_count": len(session_handles)}),
    )

    participants = [NegotiationParticipant(id=handle, name=handle) for handle in session_handles]
    joined_intents = "\n".join(
        f"- {handle}: {intent}" for handle, intent in zip(session_handles, intents, strict=False)
    )

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
                content=json.dumps(
                    {
                        "round": result.steps,
                        "plan": plan,
                        "assignments": assignments,
                        "timedout": result.timedout,
                        "broken": result.broken,
                    }
                ),
            )
            async with async_session_maker() as db:
                await db.execute(
                    update(Room).where(Room.name == room_name).values(coordination_state="complete")
                )
                await db.commit()
        except Exception as exc:
            logger.error("Negotiation pipeline failed for room %s: %s", room_name, exc)
            await _post_message(
                room_name,
                message_type="coordination_error",
                content=json.dumps({"error": str(exc)}),
            )
            async with async_session_maker() as db:
                await db.execute(
                    update(Room).where(Room.name == room_name).values(coordination_state="failed")
                )
                await db.commit()
        finally:
            _state.pop(room_name, None)
            _pipelines.pop(room_name, None)

    asyncio.ensure_future(_run_pipeline())


async def on_agent_response(room_name: str, handle: str, content: str) -> None:
    """Called by messages route when an agent posts in a negotiating room.

    CFN mode: collects reply, triggers decide when all agents have replied.
    NegMAS mode: routes reply to the matching RoomNegotiator.
    """
    # CFN mode — collect replies and trigger decide when all have arrived
    cfn = _cfn_state.get(room_name)
    if cfn is not None:
        should_decide = False
        async with cfn.lock:
            if handle in cfn.pending_replies:
                # Parse structured reply if possible; fall back to raw content
                reply_data = _parse_agent_reply(handle, content)
                cfn.pending_replies[handle] = reply_data
                logger.debug(
                    "CFN room %s: collected reply from %s (%d/%d)",
                    room_name,
                    handle,
                    sum(1 for v in cfn.pending_replies.values() if v is not None),
                    len(cfn.pending_replies),
                )
                all_received = all(v is not None for v in cfn.pending_replies.values())
                if all_received:
                    should_decide = True
        if should_decide:
            asyncio.ensure_future(_cfn_decide_round(room_name))
        return

    # NegMAS mode — route to the active pipeline's negotiator registry
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


def _parse_agent_reply(handle: str, content: str) -> dict:
    """Try to parse agent reply content as a CFN AgentReply dict.

    Expected formats (in order of preference):
      1. JSON with "action" key: {"action": "accept"|"reject"|"counter_offer", "offer": {...}}
      2. Plain text: treat as "reject" with the text stored in offer context

    Always returns a dict with at least {"agent_id": handle, "action": ...}.
    """
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            # ProposeReply format: {"offer": {...}} — no action key
            # Sent by `mycelium message propose KEY=VALUE`
            if "offer" in parsed and "action" not in parsed:
                return {"agent_id": handle, "action": "counter_offer", "offer": parsed["offer"]}

            if "action" in parsed:
                action = parsed["action"]
                # Map "end" (old NegMAS action) to "reject" for CFN compat
                if action not in ("accept", "reject", "counter_offer"):
                    action = "reject"
                result: dict = {"agent_id": handle, "action": action}
                if parsed.get("offer"):
                    result["offer"] = parsed["offer"]
                return result
    except (json.JSONDecodeError, TypeError):
        pass

    # Plain text reply — treat as reject (agent is responding but not accepting)
    return {"agent_id": handle, "action": "reject"}


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
            if not agent_handles:
                # Check top-level participant_id (NegMAS inline format)
                pid = parsed.get("participant_id")
                if pid:
                    agent_handles = [pid]
            if not agent_handles:
                # Check nested payload.participant_id (CFN format)
                pid = (parsed.get("payload") or {}).get("participant_id")
                if pid:
                    agent_handles = [pid]
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
