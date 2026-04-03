# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Multi-agent coordination service.

Manages the join-window → tick-based negotiation lifecycle for Mycelium rooms.
State is in-memory (v1) — cleared on server restart.

CFN mode (requires COGNITION_FABRIC_NODE_URL + room.mas_id + room.workspace_id):
  1. First agent joins → start join timer
  2. Timer fires → call CFN start, fan out coordination_ticks to ALL agents at once
  3. Agents reply → replies collected in _cfn_state[room_name].pending_replies
  4. Once ALL agents reply → call CFN decide
  5. CFN returns "ongoing" → fan out next round; "agreed" → post coordination_consensus
  6. Repeat until agreed or max steps exhausted

If CFN is not configured on the room, coordination fails immediately with a
coordination_error message and the room is set to "failed" state.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

import asyncpg
from sqlalchemy import select, update

from app.bus import agent_channel, notify, room_channel
from app.config import settings
from app.database import async_session_maker
from app.models import Message, Room, Session

logger = logging.getLogger(__name__)


# ── CFN mode state ─────────────────────────────────────────────────────────────


# How long to wait for agent replies before calling /decide with whatever we have.
# The IOC's BatchCallbackRunner uses a 30s per-round timeout; we fire slightly earlier
# so the backend stays in sync with the IOC's internal loop.
_CFN_ROUND_TIMEOUT_SECS = 25


@dataclass
class _CfnRoundState:
    session_id: str
    workspace_id: str
    mas_id: str
    agents: list[str]  # agent handles expected each round
    pending_replies: dict[str, dict | None] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    round_timeout_task: asyncio.Task | None = field(default=None)


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
    """Tick 0: launch CFN negotiation. Errors if CFN not configured on the room."""
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
        return

    use_cfn = bool(
        settings.COGNITION_FABRIC_NODE_URL
        and room is not None
        and room.mas_id
        and room.workspace_id
    )

    if not use_cfn:
        logger.error(
            "Coordination requested for %s but CFN not configured (no COGNITION_FABRIC_NODE_URL "
            "or room.mas_id/workspace_id not set)",
            room_name,
        )
        await _post_message(
            room_name,
            message_type="coordination_error",
            content=json.dumps(
                {"error": "CFN coordination required but not configured for this room"}
            ),
        )
        async with async_session_maker() as db:
            await db.execute(
                update(Room).where(Room.name == room_name).values(coordination_state="failed")
            )
            await db.commit()
        return

    await _run_cfn_negotiation(room_name, room, session_handles, intents)


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
        logger.error("CFN start_negotiation returned empty result for %s", room_name)
        await _finish_cfn(room_name, plan="CFN start failed", assignments={}, broken=True)
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

    # /initiate response is SSTP-wrapped: first-round messages are in payload.messages
    initiate_payload = result.get("payload", {})
    messages = initiate_payload.get("messages", result.get("messages", []))

    if not messages:
        logger.error("CFN initiate returned no messages for %s", room_name)
        await _finish_cfn(
            room_name, plan="CFN initiate returned no messages", assignments={}, broken=True
        )
        return

    # Fan out first-round ticks; pending_replies tracks only who got a tick this round
    addressed = await _fan_out_cfn_messages(room_name, messages, result.get("semantic_context", {}))
    async with state.lock:
        state.pending_replies = {h: None for h in addressed}
    _reset_round_timeout(room_name, state)


def _reset_round_timeout(room_name: str, state: "_CfnRoundState") -> None:
    """Cancel any existing round timeout and start a new one."""
    if state.round_timeout_task and not state.round_timeout_task.done():
        state.round_timeout_task.cancel()
    state.round_timeout_task = asyncio.ensure_future(_round_timeout(room_name))


async def _round_timeout(room_name: str) -> None:
    """Fire /decide with whatever replies exist after _CFN_ROUND_TIMEOUT_SECS.

    The IOC's BatchCallbackRunner uses a 30s per-round timeout and auto-advances
    when it fires.  We call /decide slightly earlier so the backend stays in sync
    with the IOC's internal loop rather than waiting forever for all replies.
    """
    await asyncio.sleep(_CFN_ROUND_TIMEOUT_SECS)
    state = _cfn_state.get(room_name)
    if not state:
        return
    logger.debug("CFN round timeout fired for %s — calling decide with partial replies", room_name)
    await _cfn_decide_round(room_name)


async def _fan_out_cfn_messages(
    room_name: str,
    messages: list[dict],
    parent_semantic_context: dict | None = None,
) -> list[str]:
    """Post coordination_tick for each agent listed in CFN messages.

    Each message is an SSTPNegotiateMessage dict.  The negotiation space
    (issues / options_per_issue) lives in semantic_context, the per-round
    decision request lives in payload.

    Returns the list of participant_ids that received a tick this round.
    """
    addressed: list[str] = []
    for msg in messages:
        payload = msg.get("payload", msg)
        participant_id = payload.get("participant_id")
        if not participant_id:
            continue

        # Negotiation space: prefer per-message semantic_context, fall back to
        # the parent envelope's semantic_context (passed from /initiate response).
        sc = msg.get("semantic_context") or parent_semantic_context or {}
        issues = sc.get("issues") or payload.get("issues")
        issue_options = sc.get("options_per_issue") or payload.get("options_per_issue")

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
                        "issue_options": issue_options,
                        "issues": issues,
                    }
                }
            ),
        )
        addressed.append(participant_id)
    return addressed


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

    # /decide response is flat: {"session_id", "status", "round", "messages"|"final_result"}
    status = result.get("status", "")

    if status in ("agreed",):
        final_result = result.get("final_result", {})
        # final_result is an SSTPCommitMessage dict; agreement is in payload.agreement
        final_payload = final_result.get("payload", {}) if isinstance(final_result, dict) else {}
        final_agreement = final_payload.get("agreement") or final_result.get("agreement") or []
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

    elif status == "ongoing":
        messages = result.get("messages", [])
        addressed = await _fan_out_cfn_messages(room_name, messages)
        async with state.lock:
            state.pending_replies = {h: None for h in addressed}
        _reset_round_timeout(room_name, state)

    else:
        # Unknown / failed status
        logger.warning("CFN decide returned status=%s for %s", status, room_name)
        await _finish_cfn(
            room_name, plan=f"Negotiation ended: {status}", assignments={}, broken=True
        )


async def _finish_cfn(room_name: str, plan: str, assignments: dict, broken: bool) -> None:
    """Post consensus and clean up CFN state."""
    state = _cfn_state.pop(room_name, None)
    if state and state.round_timeout_task and not state.round_timeout_task.done():
        state.round_timeout_task.cancel()
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


async def on_agent_response(room_name: str, handle: str, content: str) -> None:
    """Called by messages route when an agent posts in a negotiating room.

    CFN mode only: collects reply, triggers decide when all agents have replied.
    """
    cfn = _cfn_state.get(room_name)
    if cfn is None:
        return

    should_decide = False
    async with cfn.lock:
        if handle in cfn.pending_replies:
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
        # All replies in — cancel the timeout so it doesn't double-fire
        if cfn.round_timeout_task and not cfn.round_timeout_task.done():
            cfn.round_timeout_task.cancel()
        asyncio.ensure_future(_cfn_decide_round(room_name))


def _parse_agent_reply(handle: str, content: str) -> dict:
    """Try to parse agent reply content as a CFN AgentReply dict.

    Expected formats (in order of preference):
      1. JSON with "action" key: {"action": "accept"|"reject"|"counter_offer", "offer": {...}}
      2. JSON with "offer" key only: treated as counter_offer
      3. Plain text: treat as "reject"

    Always returns a dict with at least {"agent_id": handle, "action": ...}.
    """
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            if "offer" in parsed and "action" not in parsed:
                return {"agent_id": handle, "action": "counter_offer", "offer": parsed["offer"]}

            if "action" in parsed:
                action = parsed["action"]
                if action not in ("accept", "reject", "counter_offer"):
                    action = "reject"
                result: dict = {"agent_id": handle, "action": action}
                if parsed.get("offer"):
                    result["offer"] = parsed["offer"]
                return result
    except (json.JSONDecodeError, TypeError):
        pass

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
        parsed_url = urlparse(settings.DATABASE_URL)
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed_url.hostname,
            port=parsed_url.port or 5432,
            user=parsed_url.username,
            password=parsed_url.password,
            database=parsed_url.path.lstrip("/"),
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
