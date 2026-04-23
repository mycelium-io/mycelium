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
from sqlalchemy import delete, select, update

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
    deciding: bool = field(default=False)  # guard against double-decide


# {room_name: _CfnRoundState}
_cfn_state: dict[str, _CfnRoundState] = {}

# {room_name: asyncio.Task}
# Tracks in-flight `start_join_timer` tasks so room deletion can cancel them
# before the join window fires `_run_tick` for an already-deleted room.
_join_timer_tasks: dict[str, asyncio.Task] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_cfn_decide_response(result: dict) -> dict:
    """Normalize CFN ``/semantic-negotiation/decide`` JSON so we can read status + agreement.

    The IOC node returns ``SemanticNegotiationPipeline.execute()`` output:

    - **Terminal:** top-level ``status``, ``session_id``, ``round``, and ``final_result``
      where ``final_result`` is the SSTP commit (``semantic_context.final_agreement``, etc.).
    - Some responses embed the commit only under ``messages[]``.

    Without flattening ``final_result``, agreement lives only inside the nested commit and
    top-level ``semantic_context`` is missing — :meth:`_cfn_decide_round` would see empty
    assignments.
    """
    if not isinstance(result, dict):
        return result

    # 1) Commit envelope only in messages[] (e.g. alternate CFN serialization)
    raw_messages = result.get("messages")
    if isinstance(raw_messages, list):
        for m in raw_messages:
            if not isinstance(m, dict):
                continue
            sc = m.get("semantic_context")
            if isinstance(sc, dict) and sc.get("final_agreement") is not None:
                return m
            if m.get("kind") == "commit":
                return m

    # 2) Standard execute() terminal: merge commit envelope up for stable parsing
    fr = result.get("final_result")
    if isinstance(fr, dict) and (
        fr.get("semantic_context") is not None or fr.get("kind") == "commit"
    ):
        merged = {**result, **fr}
        if isinstance(fr.get("semantic_context"), dict):
            merged["semantic_context"] = fr["semantic_context"]
        if isinstance(fr.get("payload"), dict):
            merged["payload"] = fr["payload"]
        return merged

    return result


async def start_join_timer(room_name: str, deadline: datetime) -> None:
    """Sleep until join window closes, then run tick 0."""
    sleep_secs = (deadline - _utcnow()).total_seconds()
    if sleep_secs > 0:
        await asyncio.sleep(sleep_secs)
    await _run_tick(room_name, tick=0)


def schedule_join_timer(room_name: str, deadline: datetime) -> asyncio.Task:
    """Schedule ``start_join_timer`` and register the task for later cancellation.

    Callers should prefer this over a bare ``asyncio.ensure_future(start_join_timer(...))``
    so :func:`teardown_for_namespace` can cancel a still-pending join window
    when the room is deleted.
    """
    task = asyncio.ensure_future(start_join_timer(room_name, deadline))
    _join_timer_tasks[room_name] = task

    def _clear(t: asyncio.Task, _name: str = room_name) -> None:
        # Remove only if this exact task is still the registered one — guards
        # against a re-scheduled timer for the same room replacing us.
        if _join_timer_tasks.get(_name) is t:
            _join_timer_tasks.pop(_name, None)

    task.add_done_callback(_clear)
    return task


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
    from app.services.cfn_negotiation import CfnNegotiationError, start_negotiation

    joined_intents = "\n".join(
        f"- {handle}: {intent}" for handle, intent in zip(session_handles, intents, strict=False)
    )
    agents = [{"id": h, "name": h} for h in session_handles]
    # Use room_name as CFN session_id — it's unique per session room and stable.
    # mas_id is shared across all sessions in the namespace so it can't be used here.
    session_id = room_name

    await _post_message(
        room_name,
        message_type="coordination_start",
        content=json.dumps({"round": 0, "agent_count": len(session_handles)}),
    )

    try:
        result = await start_negotiation(
            session_id=session_id,
            content_text=joined_intents,
            agents=agents,
            workspace_id=room.workspace_id,
            mas_id=room.mas_id,
        )
    except CfnNegotiationError as exc:
        logger.error("CFN start_negotiation failed for %s: %s", room_name, exc)
        await _finish_cfn(room_name, plan=f"CFN start failed — {exc}", assignments={}, broken=True)
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

    # /start returns a flat dict: {"status": "initiated", "messages": [...], "issues": [...], ...}
    messages = result.get("messages", [])
    issues = result.get("issues")
    options_per_issue = result.get("options_per_issue")

    if not messages:
        logger.error("CFN initiate returned no messages for %s", room_name)
        await _finish_cfn(
            room_name, plan="CFN initiate returned no messages", assignments={}, broken=True
        )
        return

    # Fan out first-round ticks; pending_replies tracks only who got a tick this round
    addressed = await _fan_out_cfn_messages(
        room_name,
        messages,
        all_agents=session_handles,
        parent_issues=issues,
        parent_options_per_issue=options_per_issue,
    )
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
    all_agents: list[str] | None = None,
    parent_issues: list | None = None,
    parent_options_per_issue: dict | None = None,
) -> list[str]:
    """Post coordination_tick for each agent listed in CFN messages.

    BatchCallbackRunner always emits a single broadcast message per round with
    ``payload.participant_id == "server"``.  When a broadcast is detected, the
    tick is sent to every agent in ``all_agents`` and each agent's individual
    ``next_proposer_id`` eligibility is conveyed via ``can_counter_offer``.

    Returns the list of agent handles that received a tick this round.
    """
    addressed: list[str] = []
    for msg in messages:
        payload = msg.get("payload", msg)
        participant_id = payload.get("participant_id")

        # BatchCallbackRunner uses participant_id="server" for broadcast rounds.
        is_broadcast = participant_id in (None, "", "server", "broadcast")

        # Negotiation space: prefer per-message semantic_context, fall back to
        # the top-level issues/options passed from the /start response.
        sc = msg.get("semantic_context") or {}
        issues = sc.get("issues") or parent_issues
        issue_options = sc.get("options_per_issue") or parent_options_per_issue

        next_proposer_id = payload.get("next_proposer_id")

        if is_broadcast and all_agents:
            # Fan out one tick per agent; mark who is authorised to counter_offer.
            for handle in all_agents:
                await _post_message(
                    room_name,
                    message_type="coordination_tick",
                    content=json.dumps(
                        {
                            "payload": {
                                "participant_id": handle,
                                "round": payload.get("round"),
                                "action": payload.get("action"),
                                "allowed_actions": payload.get("allowed_actions", []),
                                "can_counter_offer": handle == next_proposer_id,
                                "current_offer": payload.get("current_offer"),
                                "proposer_id": payload.get("proposer_id"),
                                "next_proposer_id": next_proposer_id,
                                "issue_options": issue_options,
                                "issues": issues,
                            }
                        }
                    ),
                )
            addressed.extend(all_agents)
        elif not is_broadcast and participant_id:
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
                            "can_counter_offer": participant_id == next_proposer_id,
                            "current_offer": payload.get("current_offer"),
                            "proposer_id": payload.get("proposer_id"),
                            "next_proposer_id": next_proposer_id,
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
    from app.services.cfn_negotiation import CfnNegotiationError, decide_negotiation

    state = _cfn_state.get(room_name)
    if not state:
        return

    # Guard against double-decide (timeout + agent-triggered firing concurrently).
    async with state.lock:
        if state.deciding:
            return
        state.deciding = True

    agent_replies = []
    for handle, reply_data in state.pending_replies.items():
        if reply_data is None:
            # Agent timed out / no structured reply — default to reject.
            # participant_id is required: CFN's BatchCallbackRunner keys reply
            # lookup on that field, and a missing value makes the whole batch
            # mismatch, dropping any other agent's counter-offer in the same
            # round (same failure mode as #105, different code path).
            agent_replies.append({"agent_id": handle, "participant_id": handle, "action": "reject"})
        else:
            agent_replies.append(reply_data)

    try:
        result = await decide_negotiation(
            session_id=state.session_id,
            agent_replies=agent_replies,
            workspace_id=state.workspace_id,
            mas_id=state.mas_id,
        )
    except CfnNegotiationError as exc:
        logger.error("CFN decide_negotiation failed for %s: %s", room_name, exc)
        await _finish_cfn(room_name, plan=f"CFN decide failed — {exc}", assignments={}, broken=True)
        return

    try:
        if not isinstance(result, dict):
            logger.error("CFN decide returned non-dict for %s: %s", room_name, type(result))
            await _finish_cfn(
                room_name, plan="CFN decide returned invalid response", assignments={}, broken=True
            )
            return

        result = _normalize_cfn_decide_response(result)

        # CFN returns a nested envelope: status lives in result["payload"]["status"]
        # and the agreement in result["semantic_context"]["final_agreement"].
        # Fall back to top-level keys for backward compatibility.
        payload = result.get("payload", {})
        status = payload.get("status", result.get("status", ""))

        if status in ("agreed",):
            final_result = result.get("final_result", {})
            # final_result is an SSTPCommitMessage dict.
            # Agreement is in semantic_context.final_agreement (list of {issue_id, chosen_option}).
            if isinstance(final_result, dict):
                sc = final_result.get("semantic_context") or {}
                raw_agreement = sc.get("final_agreement") or []
                # Fallback: some versions embed it in payload.trace.final_agreement
                if not raw_agreement:
                    trace = (final_result.get("payload") or {}).get("trace") or {}
                    raw_agreement = trace.get("final_agreement") or []
            else:
                raw_agreement = []
            if isinstance(raw_agreement, list):
                agreement = {
                    item["issue_id"]: item.get("chosen_option", "")
                    for item in raw_agreement
                    if isinstance(item, dict) and "issue_id" in item
                }
            else:
                agreement = {}
            plan = "; ".join(f"{k}={v}" for k, v in agreement.items()) if agreement else "agreed"
            await _finish_cfn(room_name, plan=plan, assignments=agreement, broken=False)

        elif status == "ongoing":
            messages = result.get("messages", [])
            addressed = await _fan_out_cfn_messages(
                room_name,
                messages,
                all_agents=state.agents,
            )
            async with state.lock:
                state.pending_replies = {h: None for h in addressed}
                state.deciding = False
            _reset_round_timeout(room_name, state)

        else:
            # Unknown / failed status
            logger.warning("CFN decide returned status=%s for %s", status, room_name)
            await _finish_cfn(
                room_name, plan=f"Negotiation ended: {status}", assignments={}, broken=True
            )
    except Exception as exc:
        logger.exception("Unhandled error processing CFN decide response for %s", room_name)
        await _finish_cfn(
            room_name, plan=f"CFN response processing failed — {exc}", assignments={}, broken=True
        )


async def teardown_for_namespace(namespace_name: str, child_room_names: list[str]) -> None:
    """Tear down all in-memory CFN state for a namespace and its child sessions.

    Called from ``DELETE /rooms/{room_name}`` to prevent cross-test (and
    cross-deletion) interference: without this, a deleted room's
    ``_cfn_state`` entry keeps its ``round_timeout_task`` alive and continues
    posting ``coordination_tick`` messages to the (recreated) room, and a
    pending ``start_join_timer`` will fire ``_run_tick`` against a now-empty
    DB which produces a stream of confused log entries.

    For every active room (the namespace itself plus every child session
    room provided), this:

      1. Cancels the pending ``start_join_timer`` task, if any.
      2. Cancels the active CFN ``round_timeout_task`` and pops the
         ``_cfn_state`` entry.
      3. Posts a ``coordination_consensus`` message with ``broken=True`` so
         any SSE subscribers (agents waiting on a tick) are notified the
         negotiation has been aborted.

    The caller is responsible for the actual DB row deletes.
    """
    affected = [namespace_name, *child_room_names]
    for room_name in affected:
        # 1. Cancel any pending join timer.
        join_task = _join_timer_tasks.pop(room_name, None)
        if join_task is not None and not join_task.done():
            join_task.cancel()

        # 2. Cancel any active CFN round and drop the in-memory state.
        state = _cfn_state.pop(room_name, None)
        had_active_cfn = False
        if state is not None:
            had_active_cfn = True
            if state.round_timeout_task and not state.round_timeout_task.done():
                state.round_timeout_task.cancel()

        # 3. Notify any SSE subscribers that the negotiation was aborted.
        # We only send this for rooms that had active CFN state — there is no
        # point waking subscribers on rooms that never started negotiating.
        if had_active_cfn:
            try:
                await _post_message(
                    room_name,
                    message_type="coordination_consensus",
                    content=json.dumps(
                        {
                            "plan": "Coordination aborted — room deleted",
                            "assignments": {},
                            "broken": True,
                        }
                    ),
                )
            except Exception as exc:
                # Posting to a room that's mid-delete can race with the row
                # being removed; that's fine, just log and continue.
                logger.warning(
                    "teardown_for_namespace: failed to post abort notice for %s: %s",
                    room_name,
                    exc,
                )

    if affected:
        logger.info(
            "Coordination teardown complete for namespace %s (cleared %d rooms)",
            namespace_name,
            len(affected),
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
        # Clean up agent Session rows so a subsequent session in the same
        # namespace doesn't see stale participants and cause CFN to fail.
        await db.execute(delete(Session).where(Session.room_name == room_name))
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

    Always returns a dict with at least {"agent_id": handle, "participant_id": handle, "action": ...}.

    ``participant_id`` is required by the CE's BatchCallbackRunner which keys
    reply lookup on that field.  Without it, all replies map to "" and the
    proposer's counter-offer is never found — the standing offer never updates.
    """
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            if "offer" in parsed and "action" not in parsed:
                return {
                    "agent_id": handle,
                    "participant_id": handle,
                    "action": "counter_offer",
                    "offer": parsed["offer"],
                }

            if "action" in parsed:
                action = parsed["action"]
                if action not in ("accept", "reject", "counter_offer"):
                    action = "reject"
                result: dict = {
                    "agent_id": handle,
                    "participant_id": handle,
                    "action": action,
                }
                if parsed.get("offer"):
                    result["offer"] = parsed["offer"]
                return result
    except (json.JSONDecodeError, TypeError):
        pass

    return {"agent_id": handle, "participant_id": handle, "action": "reject"}


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
