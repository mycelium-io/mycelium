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
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from rapidfuzz import fuzz as _fuzz
from sqlalchemy import delete, select, update

from app.bus import agent_channel, notify, room_channel
from app.config import settings
from app.database import async_session_maker
from app.models import CoordinationSession, Message, Participant, Room
from app.services.metrics import (
    record_consensus,
    record_coordination_round,
    record_coordination_start,
    record_room_identity,
)
from app.services.plan import read_plan_file, set_title_from_body_if_absent, write_plan_file
from app.services.plan_compiler import compile_plan, fallback_body

logger = logging.getLogger(__name__)


# ── CFN mode state ─────────────────────────────────────────────────────────────


# How long to wait for agent replies before aborting the session.
# We wait indefinitely for replies within a round; this only fires when agents
# go completely silent (disconnected / crashed).  Using /decide with partial
# rejects caused a double-decide race that silently dropped valid counter-offers.
_CFN_ROUND_TIMEOUT_SECS = 300


# ── Round trace instrumentation (#162) ────────────────────────────────────────
#
# Per-round, per-agent telemetry that records *what actually happened* during a
# CFN negotiation round: when each agent's first response arrived (or didn't),
# whether a reply was synthesised because the watchdog fired, and which decision
# path closed the round.  Drives real latency/synthesis distributions for
# diagnosing coordination stalls.  Pure observability — no behaviour change.

DecisionPath = Literal["all_replied", "watchdog_fired", "hard_cap", "aborted"]


@dataclass
class _PerAgentTrace:
    """Per-agent record within a single round."""

    handle: str
    first_response_ms: float | None = None  # wall time agent->backend, ms
    reply_action: str | None = None  # "accept" | "reject" | "counter_offer" | None
    was_synthesised: bool = False
    adapter: str = "unknown"  # placeholder until #173 lands a shared contract


@dataclass
class _RoundTrace:
    """Trace for one round of negotiation."""

    room_name: str
    session_id: str
    mas_id: str
    workspace_id: str
    round_n: int
    n_agents: int
    started_at: float = field(default_factory=time.monotonic)  # for latency math
    started_at_wall: datetime = field(default_factory=lambda: datetime.now(UTC))
    budget_seconds: float = float(_CFN_ROUND_TIMEOUT_SECS)
    extension_count: int = 0  # currently always 0; reserved for adaptive timing work
    per_agent: dict[str, _PerAgentTrace] = field(default_factory=dict)
    decision_path: DecisionPath | None = None
    closed_at: float | None = None  # monotonic
    outcome: str | None = None  # "agreed" | "ongoing" | "timeout" | "aborted" | "error"
    # Timing decomposition.  All values are wall-time milliseconds measured
    # from ``started_at`` (round open) so they're directly comparable to
    # ``per_agent.first_response_ms`` and ``elapsed_ms``.
    #
    # Total elapsed = reply collection + CFN decide, i.e.
    #     elapsed_ms ≈ last_reply_received_ms + cfn_decide_ms
    # (with a small scheduling gap between the two).  Splitting these out lets
    # callers tell "agents were slow" apart from "CFN /decide was slow", which
    # rolling them into a single ``elapsed_ms`` cannot answer.
    last_reply_received_ms: float | None = None  # when the final reply arrived
    cfn_decide_started_ms: float | None = None  # when /decide was invoked
    cfn_decide_ms: float | None = None  # duration of the /decide HTTP call
    # CFN response shape — cheap, non-invasive proxies for "what kept CFN busy"
    # when ``cfn_decide_ms`` is large.  Mycelium has no visibility into CFN's
    # internal stages, but the response itself tells us a lot:
    #   * many ``messages`` + long decide → multi-turn mediator loop
    #   * few ``messages`` + long decide → single slow LLM call
    #   * large ``response_bytes``       → verbose internal trace
    cfn_status: str | None = None  # CFN payload status: agreed/ongoing/failed/...
    cfn_messages_count: int | None = None  # mediator messages returned (ongoing rounds)
    cfn_response_bytes: int | None = None  # size of CFN's JSON response
    # Per-stage timing breakdown returned by CFN itself (when available).  See the
    # experiment branch in ioc-cognition-fabric-node-svc / ioc-cfn-cognitive-agents
    # that adds a ``_timing`` envelope to /decide responses.  Keys are stage names
    # (e.g. ``pipeline_ms``, ``to_dict_ms``, ``thread_wait_ms``, ``in_thread_ms``,
    # ``step_negotiation_ms``).  ``None`` when CFN doesn't emit the envelope —
    # capture is tolerant so this code works against unpatched CFN images too.
    cfn_internal_timing: dict | None = None
    # Mycelium-side breakdown of the /decide HTTP call.  Populated by
    # ``services/_cfn_call_timing.py`` + ``cfn_negotiation._cfn_post``.  Keys include
    # ``client_setup_ms``, ``http_ms``, ``raise_for_status_ms``, ``json_parse_ms``,
    # ``client_close_ms``, ``response_bytes``, plus ``loop_lag_*`` summary stats
    # from a background sampler that ran concurrently with the await.  The point
    # is to attribute the gap between Mycelium's ``cfn_decide_ms`` and CFN's
    # ``route_handler_ms`` (~18-28s in our smoke tests) to the right party:
    # transport, json parsing, or a blocked Mycelium event loop.
    cfn_call_timing: dict | None = None

    def to_json(self) -> dict:
        """Serialise for structured logging / API."""
        elapsed_ms = (
            round((self.closed_at - self.started_at) * 1000, 1)
            if self.closed_at is not None
            else None
        )
        synthesised = sorted(h for h, t in self.per_agent.items() if t.was_synthesised)
        return {
            "room": self.room_name,
            "session_id": self.session_id,
            "mas_id": self.mas_id,
            "workspace_id": self.workspace_id,
            "round_n": self.round_n,
            "n_agents": self.n_agents,
            "started_at": self.started_at_wall.isoformat(),
            "elapsed_ms": elapsed_ms,
            "budget_seconds": self.budget_seconds,
            "extension_count": self.extension_count,
            "decision_path": self.decision_path,
            "outcome": self.outcome,
            "synthesised_count": len(synthesised),
            "synthesised_handles": synthesised,
            "last_reply_received_ms": (
                round(self.last_reply_received_ms, 1)
                if self.last_reply_received_ms is not None
                else None
            ),
            "cfn_decide_started_ms": (
                round(self.cfn_decide_started_ms, 1)
                if self.cfn_decide_started_ms is not None
                else None
            ),
            "cfn_decide_ms": (
                round(self.cfn_decide_ms, 1) if self.cfn_decide_ms is not None else None
            ),
            "cfn_status": self.cfn_status,
            "cfn_messages_count": self.cfn_messages_count,
            "cfn_response_bytes": self.cfn_response_bytes,
            "cfn_internal_timing": self.cfn_internal_timing,
            "cfn_call_timing": self.cfn_call_timing,
            "per_agent": {
                h: {
                    "first_response_ms": (
                        round(t.first_response_ms, 1) if t.first_response_ms is not None else None
                    ),
                    "reply_action": t.reply_action,
                    "was_synthesised": t.was_synthesised,
                    "adapter": t.adapter,
                }
                for h, t in self.per_agent.items()
            },
        }


# Ring buffer of completed round traces, exposed via
# ``GET /api/coordination/round-traces``.  Bounded to keep memory predictable
# under long-running deployments; defaults to 1024 rounds (plenty for a batch
# run that scrapes the buffer between iterations).
ROUND_TRACE_BUFFER_SIZE = 1024
_completed_round_traces: deque[dict] = deque(maxlen=ROUND_TRACE_BUFFER_SIZE)


def get_round_traces(limit: int | None = None) -> list[dict]:
    """Return completed round traces, oldest-first.  Used by the trace API."""
    items = list(_completed_round_traces)
    if limit is not None and limit >= 0:
        # Note: items[-0:] == items[:] (returns everything), so handle 0 explicitly.
        items = items[-limit:] if limit > 0 else []
    return items


def clear_round_traces() -> None:
    """Empty the round trace buffer.  Used by the trace API and tests."""
    _completed_round_traces.clear()


def _emit_round_trace(trace: _RoundTrace) -> None:
    """Push a closed round trace into the ring buffer and structured log."""
    record = trace.to_json()
    _completed_round_traces.append(record)
    # Single-line JSON so log aggregators / `jq` can ingest directly.
    logger.info("CFN_ROUND_TRACE %s", json.dumps(record, sort_keys=True))


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
    # Metrics tracking
    round_num: int = field(default=0)
    round_start_time: float = field(default=0.0)
    session_start_time: float = field(default=0.0)
    round_n: int = 0  # round index from #162 trace machinery (0-based, ours)
    current_trace: _RoundTrace | None = None
    # CFN-reported round + negotiation context used by the counter-offer
    # validation path from #174 (separate from round_n, which is internal to
    # the trace).
    current_round: int = 0
    current_offer: dict | None = None
    issues: list[str] | None = None
    issue_options: dict[str, list[str]] | None = None
    next_proposer_id: str | None = None
    # Round budget passed to CFN /start. Forwarded into ticks so agents can
    # see how many rounds remain and decide whether to walk away with no
    # agreement.
    n_steps_total: int = 0
    # Per-agent record of last round's action ("accept" | "reject" |
    # "counter_offer" | "timeout"). Forwarded into the next tick as
    # ``your_last_action`` so agents don't have to reverse-engineer state.
    last_actions: dict[str, str] = field(default_factory=dict)
    # Short label for what happened in the previous round: "first_round",
    # "proposer_countered", "rejected_by_<id>", or "agreed". Forwarded into
    # the next tick as ``prior_round_outcome`` so agents stop describing
    # their own offer as "reflected back".
    last_round_outcome: str = "first_round"
    # Negotiation context captured for the plan compiler (consensus → plan).
    # _finish_cfn only receives the session room name; the agents' opening
    # positions and participant handles aren't otherwise reachable there.
    joined_intents: str = ""
    session_handles: list[str] = field(default_factory=list)


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

    If a timer is already armed for this room, cancel it first — this lets
    subsequent joins extend the window by rescheduling with a new deadline
    instead of stacking timers (which would race and fire CFN early).
    """
    existing = _join_timer_tasks.get(room_name)
    if existing is not None and not existing.done():
        existing.cancel()
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
        # room_name here is a session display name like "{parent}:session:{short}".
        # Resolve it to the CoordinationSession entity.
        if ":session:" in room_name:
            parent, _, short_id = room_name.partition(":session:")
            coord_result = await db.execute(
                select(CoordinationSession).where(
                    CoordinationSession.parent_room_name == parent,
                    CoordinationSession.short_id == short_id,
                )
            )
            coord_session = coord_result.scalar_one_or_none()
        else:
            coord_session = None

        if coord_session is None:
            logger.warning("No coordination session for room %s at tick %d", room_name, tick)
            return

        result = await db.execute(
            select(Participant)
            .where(Participant.coordination_session_id == coord_session.id)
            .order_by(Participant.joined_at)
        )
        sessions = list(result.scalars().all())

        if not sessions:
            logger.warning("No participants for room %s at tick %d", room_name, tick)
            return

        session_handles = [s.agent_handle for s in sessions]
        intents = [s.intent or "" for s in sessions]

        # mas_id / workspace_id live on the coord session (inherited from parent
        # at spawn). Fall back to the parent room if for any reason the coord
        # session row is missing them (legacy data).
        mas_id = coord_session.mas_id
        workspace_id = coord_session.workspace_id
        if not mas_id or not workspace_id:
            parent_room_result = await db.execute(
                select(Room).where(Room.name == coord_session.parent_room_name)
            )
            parent_room = parent_room_result.scalar_one_or_none()
            if parent_room is not None:
                mas_id = mas_id or parent_room.mas_id
                workspace_id = workspace_id or parent_room.workspace_id

        await db.execute(
            update(CoordinationSession)
            .where(CoordinationSession.id == coord_session.id)
            .values(state="negotiating")
        )
        await db.commit()

    if tick != 0:
        return

    if not settings.COGNITION_FABRIC_NODE_URL or not mas_id or not workspace_id:
        logger.error(
            "Coordination requested for %s but CFN not configured (no COGNITION_FABRIC_NODE_URL "
            "or coord_session mas_id/workspace_id not set)",
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
                update(CoordinationSession)
                .where(CoordinationSession.id == coord_session.id)
                .values(state="failed")
            )
            await db.commit()
        return

    # Build a lightweight namespace-resolver shim; the rest of the negotiation
    # path only reads ``room.workspace_id`` / ``room.mas_id`` / ``room.name``,
    # so a SimpleNamespace is sufficient and avoids re-loading the Room.
    from types import SimpleNamespace

    room_for_negotiation = SimpleNamespace(
        name=coord_session.parent_room_name,
        mas_id=mas_id,
        workspace_id=workspace_id,
    )

    await _run_cfn_negotiation(
        room_name,
        room_for_negotiation,  # ty: ignore[invalid-argument-type]
        workspace_id,
        mas_id,
        session_handles,
        intents,
    )


async def _run_cfn_negotiation(
    room_name: str,
    room: Room,
    workspace_id: str,
    mas_id: str,
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

    session_start_time = time.monotonic()
    record_coordination_start(participants=len(session_handles))
    # Capture the room_name ↔ mas_id link in the snapshot so the CLI's
    # per-room tables can keep displaying both axes after the room is
    # hard-deleted from /api/rooms. We pass the parent room (room.name)
    # because the coordination counters bucket by parent room too
    # (``_parent_room`` strips ``:session:<uuid>`` suffixes downstream).
    record_room_identity(mas_id=mas_id, room_name=room.name)

    await _post_message(
        room_name,
        message_type="coordination_start",
        content=json.dumps({"round": 0, "agent_count": len(session_handles)}),
    )

    try:
        from app.config import settings

        result = await start_negotiation(
            session_id=session_id,
            content_text=joined_intents,
            agents=agents,
            workspace_id=workspace_id,
            mas_id=mas_id,
            n_steps=settings.NEGOTIATION_N_STEPS,
            room=room_name,
        )
    except CfnNegotiationError as exc:
        logger.error("CFN start_negotiation failed for %s: %s", room_name, exc)
        await _finish_cfn(room_name, plan=f"CFN start failed — {exc}", assignments={}, broken=True)
        return

    # Set up CFN round state
    state = _CfnRoundState(
        session_id=session_id,
        workspace_id=workspace_id,
        mas_id=mas_id,
        agents=session_handles[:],
        pending_replies={h: None for h in session_handles},
        round_num=1,
        round_start_time=time.monotonic(),
        session_start_time=session_start_time,
        n_steps_total=settings.NEGOTIATION_N_STEPS,
        joined_intents=joined_intents,
        session_handles=session_handles[:],
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
        _open_round_trace(state, room_name, addressed)
    _reset_round_timeout(room_name, state)


def _open_round_trace(state: "_CfnRoundState", room_name: str, addressed: list[str]) -> None:
    """Initialise the trace for a freshly-opened round.

    ``state.round_n`` is the round index *within this negotiation* — it resets
    to 0 each time ``_run_cfn_negotiation`` creates a new ``_CfnRoundState``,
    not across the room's lifetime.

    Lock contract: caller MUST hold ``state.lock`` so the trace open and the
    matching ``state.pending_replies = {...}`` reset happen atomically — a
    reply arriving between the two would otherwise land on a stale trace.
    Idempotent per round.
    """
    state.current_trace = _RoundTrace(
        room_name=room_name,
        session_id=state.session_id,
        mas_id=state.mas_id,
        workspace_id=state.workspace_id,
        round_n=state.round_n,
        n_agents=len(addressed),
        per_agent={h: _PerAgentTrace(handle=h) for h in addressed},
    )


def _close_round_trace(
    state: "_CfnRoundState",
    decision_path: DecisionPath,
    outcome: str,
) -> None:
    """Stamp closing fields on the current trace and emit it.

    Safe to call from any code path that closes a round (agreed, ongoing,
    error, abort).  Idempotent: no-op if there is no current trace, and
    clears ``state.current_trace`` after emit so a second call is silent.

    Lock contract: caller must hold ``state.lock`` *only* on paths that
    keep the state alive afterwards (i.e. ``ongoing``, where the next round
    opens immediately).  On terminal paths (``agreed``, ``error``, abort)
    the state is popped from ``_cfn_state`` right after, so no other
    coroutine can race on ``current_trace`` and the lock isn't needed.
    """
    trace = state.current_trace
    if trace is None:
        return
    trace.decision_path = decision_path
    trace.outcome = outcome
    trace.closed_at = time.monotonic()
    _emit_round_trace(trace)
    state.current_trace = None


def _reset_round_timeout(room_name: str, state: "_CfnRoundState") -> None:
    """Cancel any existing round timeout and start a new one."""
    if state.round_timeout_task and not state.round_timeout_task.done():
        state.round_timeout_task.cancel()
    state.round_timeout_task = asyncio.ensure_future(_round_timeout(room_name))


async def _round_timeout(room_name: str) -> None:
    """Abort the session if agents go silent for _CFN_ROUND_TIMEOUT_SECS.

    We wait for all agents to reply within a round.  Calling /decide with
    partial reject placeholders caused a double-decide race: the timeout fired,
    reset pending_replies, and then the real replies landed in the new round's
    slot — triggering a second /decide on an already-consumed SAO step, which
    CFN silently dropped.  Instead, a long silence means the session is dead.
    """
    await asyncio.sleep(_CFN_ROUND_TIMEOUT_SECS)
    state = _cfn_state.get(room_name)
    if not state:
        return
    logger.warning(
        "CFN round timeout fired for %s — agents silent for %ds, aborting session",
        room_name,
        _CFN_ROUND_TIMEOUT_SECS,
    )
    # Stamp the in-flight round trace so the analyzer can attribute the abort
    # to the watchdog instead of seeing a trace with no decision_path. The
    # trace is closed by _finish_cfn → _close_round_trace.
    trace = state.current_trace
    if trace is not None and trace.decision_path is None:
        trace.decision_path = "watchdog_fired"
    await _finish_cfn(
        room_name,
        plan="Negotiation timed out — agents did not respond",
        assignments={},
        broken=True,
    )


async def _load_shared_context_files(room_name: str, db=None) -> list[dict]:
    """Return the opt-in context files shared by every participant of a session.

    ``room_name`` is the session display name (``{parent}:session:{short}``).
    Returns ``[{"shared_by": handle, "path": ..., "sha256": ..., "content": ...}]``
    flattened across participants. Empty list if none.

    Callers in the fan-out path don't hold a session, so a fresh one is
    opened from ``async_session_maker``; tests can pass an open session.
    """
    if ":session:" not in room_name:
        return []
    parent, _, short_id = room_name.partition(":session:")
    if not parent or not short_id:
        return []

    async def _query(session) -> list[dict]:
        result = await session.execute(
            select(Participant.agent_handle, Participant.context_files)
            .join(
                CoordinationSession,
                Participant.coordination_session_id == CoordinationSession.id,
            )
            .where(
                CoordinationSession.parent_room_name == parent,
                CoordinationSession.short_id == short_id,
            )
        )
        out: list[dict] = []
        for handle, files in result.all():
            for cf in files or []:
                out.append(
                    {
                        "shared_by": handle,
                        "path": cf.get("path"),
                        "sha256": cf.get("sha256"),
                        "content": cf.get("content"),
                    }
                )
        return out

    if db is not None:
        return await _query(db)
    async with async_session_maker() as session:
        return await _query(session)


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
    try:
        shared_context = await _load_shared_context_files(room_name)
    except Exception as exc:
        logger.debug("shared_context_files load skipped for %s: %s", room_name, exc)
        shared_context = []

    # Open tasks from the parent room's plan/ namespace — surfaced to every
    # agent so the negotiated outcome stays aligned with the active plan.
    try:
        from app.services.plan import open_task_summary

        parent_room = room_name.split(":session:", 1)[0] if ":session:" in room_name else room_name
        plan_summary = open_task_summary(parent_room)
    except Exception as exc:
        logger.debug("plan_summary load skipped for %s: %s", room_name, exc)
        plan_summary = None
    # Read state once so each tick in this batch sees the same prior-round
    # snapshot; _cfn_decide_round overwrites these fields immediately before
    # calling us so the values describe what just happened.
    state_snapshot = _cfn_state.get(room_name)
    n_steps_total = state_snapshot.n_steps_total if state_snapshot else 0
    last_actions = dict(state_snapshot.last_actions) if state_snapshot else {}
    prior_round_outcome = state_snapshot.last_round_outcome if state_snapshot else "first_round"

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
                                # Negotiation budget + per-agent context so
                                # agents don't have to reverse-engineer the
                                # prior turn from action+can_counter_offer.
                                "n_steps_total": n_steps_total,
                                "your_last_action": last_actions.get(handle),
                                "prior_round_outcome": prior_round_outcome,
                                "plan_open_tasks": plan_summary,
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
                            "n_steps_total": n_steps_total,
                            "your_last_action": last_actions.get(participant_id),
                            "prior_round_outcome": prior_round_outcome,
                            "shared_context_files": shared_context,
                            "plan_open_tasks": plan_summary,
                        }
                    }
                ),
            )
            addressed.append(participant_id)

    # Update round state so validation and the status endpoint can read it.
    state = _cfn_state.get(room_name)
    if state and messages:
        last_payload = messages[-1].get("payload", messages[-1])
        if issues:
            state.issues = issues
        if issue_options:
            state.issue_options = issue_options
        round_num = last_payload.get("round")
        if round_num is not None:
            state.current_round = round_num
        current_offer = last_payload.get("current_offer")
        if current_offer is not None:
            state.current_offer = current_offer
        next_proposer_id = last_payload.get("next_proposer_id")
        if next_proposer_id is not None:
            state.next_proposer_id = next_proposer_id

    return addressed


async def _cfn_decide_round(
    room_name: str,
    decision_path: DecisionPath = "all_replied",
) -> None:
    """Called when all expected agents have replied (or the watchdog fired).

    ``decision_path`` records *why* this round is closing — used by the trace
    instrumentation to distinguish watchdog-fired rounds (where we synthesise
    rejects, the failure mode from #162) from the happy "all_replied" path.
    """
    from app.services.cfn_negotiation import (
        CfnNegotiationError,
        _extract_cfn_usage,
        decide_negotiation,
    )

    state = _cfn_state.get(room_name)
    if not state:
        return

    # Guard against double-decide (timeout + agent-triggered firing concurrently).
    async with state.lock:
        if state.deciding:
            return
        state.deciding = True

    agent_replies = []
    # Snapshot per-agent actions for the next tick's `your_last_action` field
    # and derive a short outcome label for `prior_round_outcome`. Both are
    # forwarded into ticks so agents can stop reverse-engineering the prior
    # turn from action+can_counter_offer.
    snapshot_actions: dict[str, str] = {}
    for handle, reply_data in state.pending_replies.items():
        if reply_data is None:
            # Agent timed out / no structured reply — default to reject.
            # participant_id is required: CFN's BatchCallbackRunner keys reply
            # lookup on that field, and a missing value makes the whole batch
            # mismatch, dropping any other agent's counter-offer in the same
            # round (same failure mode as #105, different code path).
            agent_replies.append({"agent_id": handle, "participant_id": handle, "action": "reject"})
            snapshot_actions[handle] = "timeout"
            # Record synthesis in the round trace so callers can measure how
            # often this happens in practice.
            if state.current_trace and handle in state.current_trace.per_agent:
                state.current_trace.per_agent[handle].was_synthesised = True
        else:
            agent_replies.append(reply_data)
            snapshot_actions[handle] = str(reply_data.get("action") or "reject")

    proposer_handle = state.next_proposer_id or ""
    proposer_action = snapshot_actions.get(proposer_handle, "")
    rejecters = [
        h
        for h, a in snapshot_actions.items()
        if h != proposer_handle and a in ("reject", "timeout")
    ]
    if proposer_action == "counter_offer":
        last_round_outcome = "proposer_countered"
    elif rejecters:
        last_round_outcome = f"rejected_by_{rejecters[0]}" if len(rejecters) == 1 else "rejected"
    elif all(a == "accept" for a in snapshot_actions.values()):
        last_round_outcome = "agreed"
    else:
        last_round_outcome = "no_consensus"
    state.last_actions = snapshot_actions
    state.last_round_outcome = last_round_outcome

    # Stamp when we entered CFN /decide.  Combined with last_reply_received_ms
    # this lets observers distinguish "agents are slow" from "CFN is slow",
    # which a single ``elapsed_ms`` field cannot answer.
    trace = state.current_trace
    if trace is not None:
        trace.cfn_decide_started_ms = (time.monotonic() - trace.started_at) * 1000.0
    decide_started_mono = time.monotonic()

    def _close_with_decide_ms(outcome: str) -> None:
        """Stamp ``cfn_decide_ms`` from the local start marker, then close.

        Local helper so all six exit points in this function stamp decide
        latency consistently without leaking the marker onto ``_RoundTrace``
        (where it would be ambiguous on aborted/teardown closes that never
        ran /decide).
        """
        if state.current_trace is not None:
            state.current_trace.cfn_decide_ms = (time.monotonic() - decide_started_mono) * 1000.0
        _close_round_trace(state, decision_path=decision_path, outcome=outcome)

    # Per-call CFN timing & Mycelium-side loop-lag sampling.
    # Install a per-call timing bucket that ``_cfn_post`` populates with
    # client_setup_ms / http_ms / json_parse_ms, and start a background
    # event-loop lag sampler so we can tell "Mycelium loop blocked" apart
    # from "transport slow" or "CFN slow" when the gap explodes.
    from app.services._cfn_call_timing import (  # local import to avoid top-level cycles
        cfn_loop_lag_start,
        cfn_loop_lag_stop,
        cfn_timing_reset,
        cfn_timing_snapshot,
        cfn_timing_stage,
    )

    cfn_timing_reset()
    _lag_sampler = await cfn_loop_lag_start(interval_ms=10.0)
    _decide_call_started_perf = time.perf_counter()
    try:
        try:
            result = await decide_negotiation(
                session_id=state.session_id,
                agent_replies=agent_replies,
                workspace_id=state.workspace_id,
                mas_id=state.mas_id,
            )
            # Stamp the moment the awaited /decide returned to Mycelium, so we
            # can attribute the leftover (cfn_decide_ms - sum_of_call_timing)
            # gap to specific Mycelium-side post-processing stages below
            # (normalize → trace stamp → fan_out_cfn_messages → close).
            from app.services._cfn_call_timing import cfn_timing_stamp

            cfn_timing_stamp(
                "decide_call_total_ms",
                round((time.perf_counter() - _decide_call_started_perf) * 1000, 2),
            )
        except CfnNegotiationError as exc:
            logger.error("CFN decide_negotiation failed for %s: %s", room_name, exc)
            round_duration_ms = (time.monotonic() - state.round_start_time) * 1000
            record_coordination_round(
                room=room_name,
                round_num=state.round_num,
                participants=len(state.agents),
                duration_ms=round_duration_ms,
            )
            _close_with_decide_ms("error")
            await _finish_cfn(
                room_name, plan=f"CFN decide failed — {exc}", assignments={}, broken=True
            )
            return
    finally:
        # Always stop the sampler and snapshot the call timing onto the trace,
        # even on the error path — partial timings (e.g. http_ms when CFN 5xx'd)
        # are exactly the data we need to diagnose those failures.
        try:
            await cfn_loop_lag_stop(_lag_sampler)
        except Exception:  # never let instrumentation break the call
            logger.exception("cfn loop-lag stop failed")
        if state.current_trace is not None:
            try:
                state.current_trace.cfn_call_timing = cfn_timing_snapshot()
            except Exception:
                logger.exception("cfn timing snapshot failed")

    # Record round completion metrics
    round_duration_ms = (time.monotonic() - state.round_start_time) * 1000
    record_coordination_round(
        room=room_name,
        round_num=state.round_num,
        participants=len(state.agents),
        duration_ms=round_duration_ms,
    )

    # Stamp from "result returned from CFN" to "trace closed" — this is where
    # any per-round post-processing lives (response normalisation, trace stamping,
    # _fan_out_cfn_messages on ongoing rounds, agreement persistence on agreed).
    _post_decide_started_perf = time.perf_counter()
    try:
        if not isinstance(result, dict):
            logger.error("CFN decide returned non-dict for %s: %s", room_name, type(result))
            _close_with_decide_ms("error")
            await _finish_cfn(
                room_name, plan="CFN decide returned invalid response", assignments={}, broken=True
            )
            return

        _extract_cfn_usage(result, "decide_negotiation", room=room_name)

        with cfn_timing_stage("normalize_response_ms"):
            result = _normalize_cfn_decide_response(result)

        # CFN returns a nested envelope: status lives in result["payload"]["status"]
        # and the agreement in result["semantic_context"]["final_agreement"].
        # Fall back to top-level keys for backward compatibility.
        payload = result.get("payload", {})
        status = payload.get("status", result.get("status", ""))

        # Stamp CFN response shape on the trace so a long ``cfn_decide_ms``
        # can be attributed to "many mediator turns" vs "one slow LLM call"
        # without needing access to CFN's internal logs.
        if state.current_trace is not None:
            state.current_trace.cfn_status = status or None
            messages_field = result.get("messages")
            if isinstance(messages_field, list):
                state.current_trace.cfn_messages_count = len(messages_field)
            try:
                state.current_trace.cfn_response_bytes = len(json.dumps(result, default=str))
            except (TypeError, ValueError):
                # Best-effort only; never let trace stamping fail the round.
                state.current_trace.cfn_response_bytes = None
            # Per-stage timing envelope, if CFN is the patched build that emits it.
            # Tolerant of any shape: only accept a flat dict[str, int|float], drop
            # everything else silently so unpatched CFN responses (which lack the
            # field entirely) and any future schema drift don't break the round.
            timing = result.get("_timing")
            if isinstance(timing, dict):
                state.current_trace.cfn_internal_timing = {
                    k: v
                    for k, v in timing.items()
                    if isinstance(k, str) and isinstance(v, int | float)
                }

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
            _close_with_decide_ms("agreed")
            await _finish_cfn(room_name, plan=plan, assignments=agreement, broken=False)

        elif status == "ongoing":
            messages = result.get("messages", [])
            addressed = await _fan_out_cfn_messages(
                room_name,
                messages,
                all_agents=state.agents,
            )
            # Close the just-finished round and open the next one atomically
            # under the state lock so on_agent_response can't slip a reply
            # into the wrong round trace.
            async with state.lock:
                _close_with_decide_ms("ongoing")
                state.round_n += 1
                state.pending_replies = {h: None for h in addressed}
                state.deciding = False
                state.round_num += 1
                state.round_start_time = time.monotonic()
                _open_round_trace(state, room_name, addressed)
            _reset_round_timeout(room_name, state)

        else:
            # Unknown / failed status
            logger.warning("CFN decide returned status=%s for %s", status, room_name)
            _close_with_decide_ms(status or "timeout")
            await _finish_cfn(
                room_name, plan=f"Negotiation ended: {status}", assignments={}, broken=True
            )
    except Exception as exc:
        logger.exception("Unhandled error processing CFN decide response for %s", room_name)
        _close_with_decide_ms("error")
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
            # Flush any in-flight round trace so we don't lose visibility into
            # the last round of an aborted negotiation (most interesting case).
            _close_round_trace(state, decision_path="aborted", outcome="aborted")

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
    # Avoid self-cancellation: if _finish_cfn is being called from inside the
    # round_timeout_task itself (the timeout path), cancelling that task here
    # raises CancelledError at the next await — which is _post_message — and
    # the terminal coordination_consensus never gets written. CancelledError
    # inherits from BaseException, not Exception, so the try/except below
    # wouldn't catch it either, and the room hangs in "negotiating" forever.
    # Only cancel the timeout task when we're NOT the one running it.
    if state and state.round_timeout_task and not state.round_timeout_task.done():
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if state.round_timeout_task is not current:
            state.round_timeout_task.cancel()
    # Defensive flush for the rare case _cfn_decide_round didn't get to it
    # (e.g. _run_cfn_negotiation called _finish_cfn directly on a startup error).
    if state and state.current_trace is not None:
        _close_round_trace(state, decision_path="aborted", outcome="error" if broken else "agreed")

    if state:
        total_duration_ms = (time.monotonic() - state.session_start_time) * 1000
        record_consensus(
            room=room_name,
            total_rounds=state.round_num,
            total_duration_ms=total_duration_ms,
            participants=len(state.agents),
            outcome="success" if not broken else "failure",
        )
    else:
        record_consensus(
            room=room_name,
            total_rounds=0,
            outcome="failure",
        )

    # Consensus → plan: compile the agreement into the room's shared plan
    # BEFORE the consensus message goes out (plan-first ordering, so a
    # ``session await`` returns once the plan exists). Fail-soft — a compiler
    # outage falls back to the raw agreement and never blocks the outcome.
    # Gated on ``not broken``: aborted/timeout consensus has no agreement to
    # compile, and the timeout-task path (always broken=True) must never reach
    # an LLM await.
    plan_file: str | None = None
    if not broken:
        parent_room = room_name.split(":session:", 1)[0] if ":session:" in room_name else room_name
        try:
            existing = read_plan_file(parent_room)
            body = await compile_plan(
                room_name=parent_room,
                assignments=assignments,
                joined_intents=state.joined_intents if state else "",
                issue_options=state.issue_options if state else None,
                existing_plan=existing,
            )
            write_plan_file(parent_room, body, updated_by="CognitiveEngine")
            set_title_from_body_if_absent(parent_room, body, updated_by="CognitiveEngine")
            plan_file = "plan/tasks.md"
        except Exception as exc:
            logger.warning(
                "_finish_cfn: plan compiler failed for %s, writing raw fallback: %s",
                room_name,
                exc,
            )
            try:
                fb_body = fallback_body(assignments)
                write_plan_file(parent_room, fb_body, updated_by="CognitiveEngine")
                set_title_from_body_if_absent(parent_room, fb_body, updated_by="CognitiveEngine")
                plan_file = "plan/tasks.md"
            except Exception:
                logger.exception("_finish_cfn: fallback plan write failed for %s", room_name)

    # ``session`` carries the session display name so room-scoped consumers
    # (the chat-channel render) can build a link to the live session view —
    # the room-scoped row has ``coordination_session_id=None`` so the link
    # target can't be derived from the row alone.
    consensus_content = json.dumps(
        {
            "plan": plan,
            "plan_file": plan_file,
            "assignments": assignments,
            "broken": broken,
            "session": room_name,
        }
    )
    parent_room_for_post = (
        room_name.split(":session:", 1)[0] if ":session:" in room_name else room_name
    )
    try:
        await _post_message(
            room_name,
            message_type="coordination_consensus",
            content=consensus_content,
        )
    except Exception as exc:
        # FK violation means the room was deleted before consensus could be written.
        # Log clearly so it's visible in traces rather than silently dropped.
        logger.error(
            "_finish_cfn: failed to write coordination_consensus for %s: %s",
            room_name,
            exc,
        )
    # Mirror the consensus to the parent room so it surfaces in the chat
    # channel alongside coordination_join. Same dual-post pattern as joins
    # (the ck_messages_one_target CHECK forbids combining both FKs in one
    # row). Non-fatal: a failure here doesn't roll back the session-scoped
    # post above. Skip when there's no parent (negotiation ran in a flat
    # room with no ``:session:`` suffix — uncommon, defensive).
    if parent_room_for_post and parent_room_for_post != room_name:
        try:
            await _post_message(
                parent_room_for_post,
                message_type="coordination_consensus",
                content=consensus_content,
            )
        except Exception as exc:
            logger.warning(
                "_finish_cfn: parent-room consensus mirror failed for %s: %s",
                parent_room_for_post,
                exc,
            )
    async with async_session_maker() as db:
        if ":session:" in room_name:
            parent, _, short_id = room_name.partition(":session:")
            await db.execute(
                update(CoordinationSession)
                .where(
                    CoordinationSession.parent_room_name == parent,
                    CoordinationSession.short_id == short_id,
                )
                .values(state="complete" if not broken else "failed")
            )
            # Clean up Participant rows so a subsequent session in the same
            # namespace doesn't see stale participants and cause CFN to fail.
            await db.execute(
                delete(Participant).where(
                    Participant.coordination_session_id.in_(
                        select(CoordinationSession.id).where(
                            CoordinationSession.parent_room_name == parent,
                            CoordinationSession.short_id == short_id,
                        )
                    )
                )
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
    corrective: dict | None = None
    out_of_turn: bool = False
    extend_timeout: bool = False
    async with cfn.lock:
        if handle in cfn.pending_replies:
            reply_data = _parse_agent_reply(handle, content, cfn.current_offer, cfn.issue_options)
            is_first_for_round = cfn.pending_replies[handle] is None
            if (
                reply_data.get("action") == "counter_offer"
                and cfn.next_proposer_id
                and handle != cfn.next_proposer_id
            ):
                out_of_turn = True
                # Leave pending_replies[handle] as None — round waits for a corrected reply.
            elif reply_data.get("action") == "invalid_keys":
                corrective = reply_data
                # Leave pending_replies[handle] as None — round waits for a corrected reply.
            else:
                # Track newness so we extend the round timer only on first
                # reply per agent per round — resubmits and duplicates don't
                # extend (a stalled agent spamming retries shouldn't be able
                # to keep the round alive forever).
                was_pending = cfn.pending_replies[handle] is None
                cfn.pending_replies[handle] = reply_data
                logger.debug(
                    "CFN room %s: collected reply from %s (%d/%d)",
                    room_name,
                    handle,
                    sum(1 for v in cfn.pending_replies.values() if v is not None),
                    len(cfn.pending_replies),
                )
                # Record per-agent timing in the round trace.  Only on the
                # *first* accepted reply per round so a resubmit doesn't mask
                # the original latency.  Rejected replies (out_of_turn /
                # invalid_keys) deliberately do not stamp — they aren't a
                # successful round contribution.
                trace = cfn.current_trace
                if trace is not None and is_first_for_round and handle in trace.per_agent:
                    slot = trace.per_agent[handle]
                    slot.first_response_ms = (time.monotonic() - trace.started_at) * 1000.0
                    if isinstance(reply_data, dict):
                        slot.reply_action = reply_data.get("action")
                all_received = all(v is not None for v in cfn.pending_replies.values())
                if all_received:
                    should_decide = True
                    # Stamp the moment the round became "ready to decide" —
                    # used by the trace to split collection vs CFN decide.
                    if trace is not None and trace.last_reply_received_ms is None:
                        trace.last_reply_received_ms = (
                            time.monotonic() - trace.started_at
                        ) * 1000.0
                elif was_pending:
                    # A new agent replied but the round isn't complete yet.
                    # Reset the round watchdog so a single slow agent doesn't
                    # blow the budget for everyone — the round only dies when
                    # the *full* timeout elapses with no further activity.
                    extend_timeout = True

    if out_of_turn:
        logger.warning(
            "CFN room %s: agent %s submitted counter_offer but next_proposer_id=%s — rejecting",
            room_name,
            handle,
            cfn.next_proposer_id,
        )
        await _post_message(
            room_name,
            message_type="coordination_tick",
            content=json.dumps(
                {
                    "error": "counter_offer_not_your_turn",
                    "instruction": (
                        f"It is not your turn to propose. Only '{cfn.next_proposer_id}' may counter-offer "
                        "this round. Use 'accept' or 'reject' instead."
                    ),
                    "payload": {"participant_id": handle},
                }
            ),
        )
        return

    if corrective:
        logger.warning(
            "CFN room %s: agent %s counter_offer rejected — bad keys %s (valid: %s)",
            room_name,
            handle,
            corrective["bad_keys"],
            corrective["valid_keys"],
        )
        await _post_message(
            room_name,
            message_type="coordination_tick",
            content=json.dumps(
                {
                    "error": "counter_offer_invalid_keys",
                    "bad_keys": corrective["bad_keys"],
                    "valid_keys": corrective["valid_keys"],
                    "instruction": (
                        "Re-submit your counter_offer using only the exact keys listed in valid_keys."
                    ),
                    "payload": {"participant_id": handle},
                }
            ),
        )
        return

    if should_decide:
        # All replies in — cancel the timeout so it doesn't double-fire
        if cfn.round_timeout_task and not cfn.round_timeout_task.done():
            cfn.round_timeout_task.cancel()
        asyncio.ensure_future(_cfn_decide_round(room_name, decision_path="all_replied"))
    elif extend_timeout:
        # A first reply landed but others are still pending. Reset the round
        # watchdog so the slow tail of agents gets the full budget too —
        # otherwise a 3+ agent room dies whenever the slowest agent takes
        # longer than the round timeout, regardless of when the others
        # replied. Only first-replies extend (resubmits/dupes don't).
        _reset_round_timeout(room_name, cfn)


_NORMALISE_RE = re.compile(r"[\s_\-]+")


def _normalise(text: str) -> str:
    """Lowercase, strip, and collapse whitespace/underscores/hyphens to a single space."""
    return _NORMALISE_RE.sub(" ", str(text).strip().lower())


def _snap_issue(raw_key: str, valid_issues: list[str], threshold: float = 80.0) -> str | None:
    """Return the best-matching valid issue for *raw_key*, or ``None``.

    Mirrors the CLI/engines five-tier snap (tiers 1-4; tier 5 embedding
    skipped). See ``mycelium.negotiate_snap.snap_issue`` for background.
    """
    if raw_key in valid_issues:
        return raw_key
    raw_lower = raw_key.lower()
    for v in valid_issues:
        if raw_lower == v.lower():
            return v
    raw_norm = _normalise(raw_key)
    for v in valid_issues:
        if raw_norm == _normalise(v):
            return v
    best_score, best_match = 0.0, None
    for v in valid_issues:
        score = _fuzz.token_set_ratio(raw_key, v)
        if score > best_score:
            best_score, best_match = score, v
    return best_match if best_score >= threshold else None


def _validate_and_fill_offer(handle: str, result: dict, current_offer: dict | None) -> dict:
    """Validate counter_offer keys and silently fill partial offers from the anchor.

    Keys that don't match exactly are snapped to the closest valid key using
    the same four-tier fuzzy logic as the CLI and CFN engines (case-insensitive,
    normalised, then token-set ratio).  Only truly unrecognisable keys produce
    the ``invalid_keys`` sentinel.
    """
    if not current_offer or not result.get("offer"):
        return result

    offer = result["offer"]
    valid_keys = list(current_offer)

    # Attempt to snap each unrecognised key to a valid one.
    remapped: dict[str, str] = {}
    unresolved: list[str] = []
    for k in offer:
        if k in current_offer:
            continue
        canonical = _snap_issue(k, valid_keys)
        if canonical is not None:
            remapped[k] = canonical
        else:
            unresolved.append(k)

    if unresolved:
        return {
            "agent_id": handle,
            "participant_id": handle,
            "action": "invalid_keys",
            "bad_keys": sorted(unresolved),
            "valid_keys": sorted(current_offer),
        }

    if remapped:
        logger.info(
            "Agent %s counter_offer keys snapped: %s",
            handle,
            {k: v for k, v in remapped.items()},
        )
        offer = {remapped.get(k, k): v for k, v in offer.items()}
        result["offer"] = offer

    # Partial offer: fill missing keys from the anchor so CFN sees a complete offer.
    if set(offer) < set(current_offer):
        logger.debug(
            "Agent %s submitted partial offer (%d/%d keys); filling from anchor",
            handle,
            len(offer),
            len(current_offer),
        )
        result["offer"] = {**current_offer, **offer}

    return result


def _parse_agent_reply(
    handle: str,
    content: str,
    current_offer: dict | None = None,
    issue_options: dict | None = None,
) -> dict:
    """Try to parse agent reply content as a CFN AgentReply dict.

    Expected formats (in order of preference):
      1. JSON with "action" key: {"action": "accept"|"reject"|"counter_offer", "offer": {...}}
      2. JSON with "offer" key only: treated as counter_offer
      3. Plain text: treat as "reject"

    When ``current_offer`` is provided, counter_offer replies are validated:
    - Keys not present in ``current_offer`` → returns ``invalid_keys`` sentinel so
      ``on_agent_response`` can post a corrective tick without advancing the round.
    - Valid but partial offers → silently filled from ``current_offer`` (agent values win).

    Always returns a dict with at least {"agent_id": handle, "participant_id": handle, "action": ...}.

    ``participant_id`` is required by the CE's BatchCallbackRunner which keys
    reply lookup on that field.  Without it, all replies map to "" and the
    proposer's counter-offer is never found — the standing offer never updates.
    """
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            if "offer" in parsed and "action" not in parsed:
                result: dict = {
                    "agent_id": handle,
                    "participant_id": handle,
                    "action": "counter_offer",
                    "offer": parsed["offer"],
                }
                return _validate_and_fill_offer(handle, result, current_offer)

            if "action" in parsed:
                action = parsed["action"]
                if action not in ("accept", "reject", "counter_offer"):
                    action = "reject"
                result = {
                    "agent_id": handle,
                    "participant_id": handle,
                    "action": action,
                }
                if parsed.get("offer"):
                    result["offer"] = parsed["offer"]
                if action == "counter_offer":
                    return _validate_and_fill_offer(handle, result, current_offer)
                return result
    except (json.JSONDecodeError, TypeError):
        pass

    return {"agent_id": handle, "participant_id": handle, "action": "reject"}


async def _post_message(room_name: str, message_type: str, content: str) -> None:
    """Insert a coordination message to DB and notify SSE subscribers."""
    async with async_session_maker() as db:
        msg_room_name: str | None = room_name
        msg_session_id: UUID | None = None
        if ":session:" in room_name:
            parent, _, short_id = room_name.partition(":session:")
            result = await db.execute(
                select(CoordinationSession.id).where(
                    CoordinationSession.parent_room_name == parent,
                    CoordinationSession.short_id == short_id,
                )
            )
            session_id = result.scalar_one_or_none()
            if session_id is not None:
                msg_room_name = None
                msg_session_id = session_id
            else:
                logger.warning(
                    "Cannot resolve session %r — no matching coordination_session row; "
                    "dropping message (type=%s)",
                    room_name,
                    message_type,
                )
                return
        msg = Message(
            room_name=msg_room_name,
            coordination_session_id=msg_session_id,
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
            if ":session:" in room_name:
                parent, _, short_id = room_name.partition(":session:")
                result = await db.execute(
                    select(Participant.agent_handle).where(
                        Participant.coordination_session_id.in_(
                            select(CoordinationSession.id).where(
                                CoordinationSession.parent_room_name == parent,
                                CoordinationSession.short_id == short_id,
                            )
                        )
                    )
                )
                agent_handles = list(result.scalars().all())
            else:
                agent_handles = []

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
