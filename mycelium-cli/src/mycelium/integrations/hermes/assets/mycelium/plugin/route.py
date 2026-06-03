# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Pure routing logic for Mycelium room messages.

Python port of the openclaw plugin's ``route.ts``. ``route_message()``
inspects a message from the room SSE stream and returns a list of
side-effect-free actions the adapter should execute. Side effects (HTTP
POST, SSE subscribe, hermes dispatch) live in :mod:`adapter`; this module
only describes "what should happen".

**CLAUDE.md rule of two — now three.** When the backend tick payload
schema changes (``backend/services/coordination.py:_fan_out_cfn_messages``
and ``_finish_cfn``), the openclaw ``route.ts`` *and* this module both
need updating. Tests under ``tests/integrations/hermes/`` keep a snapshot
of :func:`format_tick_instruction` output so the two formatters can be
diffed mechanically.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .mentions import resolve_mentions

# ── action types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Dispatch:
    """Hand a rendered prompt off to hermes's agent loop."""

    agent_id: str
    sender: str
    content: str
    message_id: str | None = None


@dataclass(frozen=True)
class SubscribeSession:
    """Open an SSE subscription against a session sub-room."""

    room_name: str


@dataclass(frozen=True)
class StashReturnAddress:
    """Record where to deliver this agent's consensus summary later."""

    session_room: str
    agent_id: str


@dataclass(frozen=True)
class NotifyHome:
    """Deliver a consensus summary back to each agent's home channel."""

    session_room: str
    agent_ids: tuple[str, ...]
    consensus_summary: str
    message_id: str | None = None


@dataclass(frozen=True)
class Ignore:
    """Explicitly drop a message with a reason (useful for tracing/tests)."""

    reason: str


RouteAction = Dispatch | SubscribeSession | StashReturnAddress | NotifyHome | Ignore


# ── room config the router needs ─────────────────────────────────────────────


@dataclass(frozen=True)
class RoomConfig:
    """Per-room slice of the platform configuration.

    Materialized from ``platforms.mycelium-room.extra.rooms[i]`` plus the
    top-level ``require_mention`` flag. Keeping this independent of the
    full platform config lets the router stay testable as a pure function.
    """

    room: str
    agents: tuple[str, ...]
    require_mention: bool = True
    backend_url: str = ""


# ── main entry point ─────────────────────────────────────────────────────────


def route_message(
    cfg: RoomConfig, msg: dict[str, Any], own_message_ids: set[str]
) -> list[RouteAction]:
    """Decide what to do with one message inbound from the room SSE stream.

    :param cfg: room-level configuration (agents, requireMention).
    :param msg: raw message object from the SSE stream.
    :param own_message_ids: IDs we've recently POSTed; matched ones are
        discarded as a side effect (mutates the caller's set).
    """
    msg_id = msg.get("id")
    if isinstance(msg_id, str) and msg_id in own_message_ids:
        own_message_ids.discard(msg_id)
        return [Ignore("own message")]

    mtype = msg.get("message_type")
    if mtype == "announce":
        return [Ignore("announce")]
    if mtype == "coordination_tick":
        return _route_tick(cfg, msg)
    if mtype == "coordination_consensus":
        return _route_consensus(cfg, msg)
    if mtype in ("coordination_join", "coordination_start"):
        return _route_join(msg)
    return _route_broadcast(cfg, msg)


# ── tick ─────────────────────────────────────────────────────────────────────


def _route_tick(cfg: RoomConfig, msg: dict[str, Any]) -> list[RouteAction]:
    raw_content = msg.get("content")
    try:
        tick_data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    except (TypeError, ValueError, json.JSONDecodeError):
        return [Ignore("tick parse error")]
    if not isinstance(tick_data, dict):
        return [Ignore("tick payload not a dict")]

    payload = tick_data.get("payload") or tick_data
    if not isinstance(payload, dict):
        return [Ignore("tick payload not a dict")]
    target = payload.get("participant_id")
    if not isinstance(target, str) or not target:
        return [Ignore("tick missing participant_id")]
    if target not in cfg.agents:
        return [Ignore(f"tick participant_id {target} not in room agents")]

    room_name = msg.get("room_name") or cfg.room
    instruction = format_tick_instruction(tick_data, room_name, target)

    actions: list[RouteAction] = []
    session_room = msg.get("room_name") or ""
    if isinstance(session_room, str) and ":session:" in session_room:
        actions.append(StashReturnAddress(session_room=session_room, agent_id=target))
    actions.append(
        Dispatch(
            agent_id=target,
            sender="CognitiveEngine",
            content=instruction,
            message_id=msg.get("id"),
        )
    )
    return actions


def format_tick_instruction(tick_data: dict[str, Any], room_name: str, target_agent: str) -> str:
    """Render a CFN tick payload as a human-readable instruction string.

    Two payload shapes from the backend:
      - normal: ``{"payload": {"round", "action", "current_offer", ...}}``
      - error:  ``{"error", "valid_keys", "bad_keys", "instruction",
                   "payload": {"participant_id"}}``

    Both must be rendered completely — this is the agent's sole source of
    tick information (CLAUDE.md). Don't strip fields that the agent needs
    to recover (e.g. ``valid_keys`` on ``counter_offer_invalid_keys``).
    """
    error_kind = tick_data.get("error")
    if isinstance(error_kind, str) and error_kind:
        return _format_error_tick(tick_data, room_name, target_agent)

    payload = tick_data.get("payload") or tick_data
    if not isinstance(payload, dict):
        payload = {}
    action = payload.get("action") or "respond"
    can_counter = payload.get("can_counter_offer") is True
    current_offer = payload.get("current_offer")
    if not isinstance(current_offer, dict):
        current_offer = {}
    round_ = payload.get("round", "?")
    n_steps_total = payload.get("n_steps_total")
    your_last_action = payload.get("your_last_action")
    prior_outcome = payload.get("prior_round_outcome")

    offer_keys = list(current_offer.keys())
    offer_summary = "\n".join(f"  {k}: {v}" for k, v in current_offer.items())

    # Round header — surface budget so the agent can decide whether to keep
    # pushing or walk away (no-agreement is a legitimate outcome).
    if isinstance(n_steps_total, int) and n_steps_total > 0:
        round_header = f"[CognitiveEngine — Round {round_} of {n_steps_total}]"
    else:
        round_header = f"[CognitiveEngine — Round {round_}]"

    context_lines: list[str] = []
    if isinstance(prior_outcome, str) and prior_outcome and prior_outcome != "first_round":
        if prior_outcome.startswith("rejected_by_"):
            who = prior_outcome.removeprefix("rejected_by_")
            outcome = f"Last round: {who} rejected the standing offer."
        elif prior_outcome == "proposer_countered":
            outcome = (
                "Last round: the designated proposer countered with a new offer (shown below)."
            )
        elif prior_outcome == "agreed":
            outcome = "Last round: all agents accepted."
        else:
            outcome = f"Last round: {prior_outcome.replace('_', ' ')}."
        context_lines.append(outcome)
    if your_last_action:
        context_lines.append(f"Your last action: {your_last_action}.")

    # Opt-in shared context files attached at session join time.
    shared = payload.get("shared_context_files")
    context_files_block: list[str] = []
    if isinstance(shared, list) and shared:
        context_files_block.append("Shared context files (opt-in by participants):")
        for cf in shared:
            if not isinstance(cf, dict):
                continue
            path = cf.get("path") or "(unknown)"
            sharer = cf.get("shared_by") or "?"
            content = cf.get("content") or ""
            context_files_block.append(f"--- {path} (shared by {sharer}) ---")
            context_files_block.append(str(content))
            context_files_block.append("--- end ---")

    # Open plan tasks from the parent room.
    plan_open_tasks = payload.get("plan_open_tasks")
    plan_block: list[str] = []
    if isinstance(plan_open_tasks, str) and plan_open_tasks:
        plan_block.append(plan_open_tasks)

    valid_keys_line = ""
    if can_counter and offer_keys:
        joined = ", ".join(f'"{k}"' for k in offer_keys)
        valid_keys_line = f"Valid offer keys (use exactly these in your counter): {joined}"

    parts: list[str] = [
        round_header,
        # The handle is repeated in the ``--handle`` CLI fragments below, but
        # surfacing it at the top of the tick is the one place every hermes
        # agent reliably sees "this is who you are in this room" — the SKILL
        # uses ``<your-handle>`` placeholders and the hermes runtime
        # doesn't otherwise plumb the mycelium handle into the persona.
        f"You are @{target_agent} in a structured negotiation in room {room_name}.",
        f"Action required: {action}",
        "You CAN propose a counter-offer." if can_counter else "You can only accept or reject.",
    ]
    if context_lines:
        parts.append("")
        parts.extend(context_lines)
    if context_files_block:
        parts.append("")
        parts.extend(context_files_block)
    if plan_block:
        parts.append("")
        parts.extend(plan_block)
    parts.extend(
        [
            "",
            "Current offer on the table:",
            offer_summary,
            "",
            valid_keys_line,
        ]
    )
    if can_counter:
        parts.append(
            f"To counter-propose, run: mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... "
            f"--room {room_name} --handle {target_agent}"
        )
    parts.extend(
        [
            f"To accept: mycelium negotiate respond accept --room {room_name} --handle {target_agent}",
            f"To reject: mycelium negotiate respond reject --room {room_name} --handle {target_agent}",
            "",
            "Explain your reasoning before running the command. Walking away with no "
            "agreement is a legitimate outcome — keep rejecting until the session ends "
            "if your hard constraints can't be met.",
        ]
    )
    # Mirror the TS formatter: empty/falsy strings are dropped (.filter(Boolean)
    # in route.ts), so blank-line separators only survive when an adjacent
    # non-empty line keeps them packaged as part of a list section.
    return "\n".join(p for p in parts if p)


def _format_error_tick(tick_data: dict[str, Any], room_name: str, target_agent: str) -> str:
    """Render a CFN error tick — invalid keys, not-your-turn, etc."""
    error_kind = str(tick_data.get("error") or "unknown_error")
    instruction = str(tick_data.get("instruction") or "")
    valid_keys_raw = tick_data.get("valid_keys")
    bad_keys_raw = tick_data.get("bad_keys")
    valid_keys: list[str] = list(valid_keys_raw) if isinstance(valid_keys_raw, list) else []
    bad_keys: list[str] = list(bad_keys_raw) if isinstance(bad_keys_raw, list) else []

    lines: list[str] = [
        f"[CognitiveEngine — error: {error_kind}]",
        f"You are @{target_agent} in room {room_name}.",
    ]
    if instruction:
        lines.extend(["", instruction])
    if bad_keys:
        joined = ", ".join(f'"{k}"' for k in bad_keys)
        lines.extend(["", f"Rejected keys: {joined}"])
    if valid_keys:
        joined = ", ".join(f'"{k}"' for k in valid_keys)
        lines.extend(["", f"Valid keys (use exactly these): {joined}"])

    if error_kind == "counter_offer_invalid_keys" and valid_keys:
        example = " ".join(f'"{k}"=VALUE' for k in valid_keys)
        lines.extend(
            [
                "",
                f"Recovery: mycelium negotiate propose {example} "
                f"--room {room_name} --handle {target_agent}",
            ]
        )
    elif error_kind == "counter_offer_not_your_turn":
        lines.extend(
            [
                "",
                f"Recovery: mycelium negotiate respond accept --room {room_name} "
                f"--handle {target_agent}",
                f"      or: mycelium negotiate respond reject --room {room_name} "
                f"--handle {target_agent}",
            ]
        )
    return "\n".join(lines)


# ── consensus ────────────────────────────────────────────────────────────────


def _identity_preamble(agent_id: str, room_name: str) -> str:
    """One-line identity header prepended to dispatches without a built-in
    handle reference.

    ``format_tick_instruction`` weaves the handle into its own header line,
    so tick dispatches don't go through here; consensus and broadcast
    paths do. Keeps the rule simple: every Dispatch hermes sees mentions
    the agent's mycelium handle exactly once, near the top.
    """
    return f"[mycelium-room] You are @{agent_id} in room {room_name}."


def _route_consensus(cfg: RoomConfig, msg: dict[str, Any]) -> list[RouteAction]:
    raw = msg.get("content")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return [Ignore("consensus parse error")]
    if not isinstance(data, dict):
        return [Ignore("consensus payload not a dict")]

    summary = format_consensus_summary(data)
    session_room_name = msg.get("room_name") or cfg.room
    actions: list[RouteAction] = [
        Dispatch(
            agent_id=aid,
            sender="CognitiveEngine",
            content=f"{_identity_preamble(aid, session_room_name)}\n\n{summary}",
            message_id=msg.get("id"),
        )
        for aid in cfg.agents
    ]

    session_room = msg.get("room_name") or ""
    if cfg.agents and isinstance(session_room, str) and ":session:" in session_room:
        actions.append(
            NotifyHome(
                session_room=session_room,
                agent_ids=tuple(cfg.agents),
                consensus_summary=summary,
                message_id=msg.get("id"),
            )
        )
    return actions


def format_consensus_summary(data: dict[str, Any]) -> str:
    """Render the ``coordination_consensus`` payload.

    Mirrors the openclaw ``formatConsensusSummary()``. The
    ``plan_file`` field is surfaced explicitly because plan-first
    ordering means it points at a file the agent can pick up
    immediately with ``mycelium plan tasks``.
    """
    plan = data.get("plan") or "No plan details"
    assignments_raw = data.get("assignments")
    assignments: dict[str, Any] = assignments_raw if isinstance(assignments_raw, dict) else {}
    broken = data.get("broken") is True
    plan_file_raw = data.get("plan_file")
    plan_file = plan_file_raw if isinstance(plan_file_raw, str) else ""

    if broken:
        return f"[CognitiveEngine — Negotiation FAILED]\n{plan}"

    plan_text = plan if isinstance(plan, str) else json.dumps(plan, indent=2, default=str)
    lines: list[str] = [
        "[CognitiveEngine — Consensus Reached!]",
        "",
        plan_text,
        "",
        "Assignments:",
        *[f"  {agent}: {task}" for agent, task in assignments.items()],
    ]
    if plan_file:
        lines.extend(
            [
                "",
                f"The consensus is now the room's shared plan (`{plan_file}`).",
                "Run `mycelium plan tasks` to see the checklist, work your tasks, and",
                "tick them off with `mycelium plan task done <id>`.",
            ]
        )
    return "\n".join(lines)


# ── join / session sub-room discovery ────────────────────────────────────────


def _route_join(msg: dict[str, Any]) -> list[RouteAction]:
    # Joins are dual-published: once on the session sub-room and once on the
    # parent room. The parent-room copy carries the session sub-room name in
    # the JSON payload's ``session`` field; the session sub-room copy has it
    # as ``room_name``. Either source is sufficient for discovery.
    room_name = msg.get("room_name") or ""
    session_room: str | None = None
    if isinstance(room_name, str) and ":session:" in room_name:
        session_room = room_name
    else:
        raw_content = msg.get("content")
        try:
            payload = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            candidate = payload.get("session")
            if isinstance(candidate, str) and ":session:" in candidate:
                session_room = candidate
    if session_room is None:
        return [Ignore("join without session sub-room")]
    actions: list[RouteAction] = [SubscribeSession(room_name=session_room)]
    sender = msg.get("sender_handle") if msg.get("message_type") == "coordination_join" else None
    if isinstance(sender, str) and sender:
        actions.append(StashReturnAddress(session_room=session_room, agent_id=sender))
    return actions


# ── broadcast (channel messaging) ────────────────────────────────────────────


def _route_broadcast(cfg: RoomConfig, msg: dict[str, Any]) -> list[RouteAction]:
    sender_raw = msg.get("sender_handle")
    sender = str(sender_raw) if isinstance(sender_raw, str) else "unknown"
    content_raw = msg.get("content")
    content = str(content_raw) if isinstance(content_raw, str) else ""
    if not content.strip():
        return [Ignore("empty content")]

    if cfg.require_mention:
        recipients = [a for a in resolve_mentions(content, list(cfg.agents)) if a != sender]
        if not recipients:
            return [Ignore("no addressed recipients (require_mention=True)")]
    else:
        recipients = [a for a in cfg.agents if a != sender]
        if not recipients:
            return [Ignore("no non-sender agents in broadcast mode")]

    return [
        Dispatch(
            agent_id=aid,
            sender=sender,
            content=f"{_identity_preamble(aid, cfg.room)}\n\n{content}",
            message_id=msg.get("id"),
        )
        for aid in recipients
    ]


__all__ = [
    "Dispatch",
    "Ignore",
    "NotifyHome",
    "RoomConfig",
    "RouteAction",
    "StashReturnAddress",
    "SubscribeSession",
    "format_consensus_summary",
    "format_tick_instruction",
    "route_message",
]
