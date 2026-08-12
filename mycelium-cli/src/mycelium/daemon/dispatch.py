# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""SSE subscription + @handle dispatch — the heart of the daemon."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import yaml
from pydantic import ValidationError

from mycelium.config import MyceliumConfig
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.mentions import resolve_mentions
from mycelium.daemon.state import DaemonState
from mycelium.filesystem import get_room_dir, list_memories, read_memory
from mycelium.integrations import get_integration
from mycelium.integrations._spawn_common import SpawnRequest, SpawnResult
from mycelium.protocol import AgentManifest

log = logging.getLogger("mycelium.daemon")

_DEPTH_WINDOW_S = 60.0

# CognitiveEngine posts coordination_tick / coordination_consensus into
# session sub-rooms (``r:session:abc``), not parent rooms — and the live
# Postgres NOTIFY for those events fires only on the sub-room channel. A
# daemon subscribed to the parent room therefore never sees them via SSE.
# Mirroring the openclaw plugin (``index.ts``), we periodically poll the
# coordination-sessions endpoint and fan out an SSE listener for each active
# session. The poll cadence is intentionally aggressive so a fresh session
# starts dispatching ticks within a single round trip; the shape is small
# (id + display_name + state) so it's cheap.
_SESSION_POLL_INTERVAL_S = 5.0
_SESSION_POLL_LIMIT = 200
# Sessions in these states are alive; we keep an SSE subscription up. Any
# other state is terminal-or-not-yet-started — drop the subscription if we
# had one so we don't pin connections on completed negotiations.
_SESSION_LIVE_STATES = frozenset({"waiting", "negotiating"})

# The backend SSE endpoint emits a `: keep-alive` comment every ~15s when a
# room is idle (see fastapi-backend/app/routes/stream.py). So a healthy
# stream is never silent longer than that. Bounding the read timeout at ~3×
# that interval means a half-open / stalled connection (peer or NAT/LB
# dropped it without a FIN — `aiter_text()` would otherwise block forever
# while the daemon still reports the room "connected") raises
# httpx.ReadTimeout within ~45s and we reconnect, instead of going silently
# deaf. Connect is bounded too so an unreachable hub fails fast.
_SSE_KEEPALIVE_S = 15.0
_SSE_READ_TIMEOUT_S = 45.0
_SSE_CONNECT_TIMEOUT_S = 10.0


# Reserved verbs at the start of an addressed message body. Anything not in
# this set goes through to claude -p as a normal prompt.
_CONTROL_ABORT = {"abort", "cancel", "stop"}
_CONTROL_STATUS = {"status"}

# CognitiveEngine is the trusted system sender for coordination_tick /
# coordination_consensus messages. We attribute autonomous spawns to it so
# logs and depth-buckets distinguish CFN-driven dispatches from agent-driven
# @-mentions.
_CFN_SENDER = "CognitiveEngine"


def _extract_body(content: str, handle: str) -> str:
    """Return the message body with the leading ``@handle`` mention stripped."""
    lower = content.lower()
    needle = f"@{handle.lower()}"
    idx = lower.find(needle)
    if idx == -1:
        return content.strip()
    return content[idx + len(needle) :].strip()


def _leading_verb(body: str) -> str | None:
    """Return the first whitespace-delimited token, lowercased, or None."""
    if not body:
        return None
    return body.split(None, 1)[0].lower()


# ── Manifest lookup (filesystem only — daemon is single-machine v0) ──────────


def list_agent_handles(room_name: str) -> list[str]:
    """List handles registered in *room_name* by scanning the local filesystem."""
    room_dir = get_room_dir(room_name)
    entries = list_memories(room_dir, prefix="agents/", limit=500)
    handles: list[str] = []
    for key, _meta, _content in entries:
        rest = key.removeprefix("agents/")
        if "/" in rest:
            continue
        handles.append(rest)
    return handles


def load_manifest(room_name: str, handle: str) -> AgentManifest | None:
    """Return the agent's manifest, or None if missing / unreadable.

    "Unreadable" (bad YAML, wrong shape, schema violation) is logged at WARNING
    so a corrupt manifest doesn't masquerade as "agent not registered" — the
    daemon would otherwise silently ignore every @handle mention with no clue
    why on the operator's side.
    """
    room_dir = get_room_dir(room_name)
    path = room_dir / "agents" / f"{handle}.md"
    result = read_memory(room_dir, f"agents/{handle}")
    if result is None:
        return None
    _, content = result
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        log.warning("manifest %s: invalid YAML — %s", path, exc)
        return None
    if not isinstance(data, dict):
        log.warning("manifest %s: expected a YAML mapping, got %s", path, type(data).__name__)
        return None
    data.setdefault("handle", handle)
    try:
        return AgentManifest(**data)
    except ValidationError as exc:
        log.warning("manifest %s: schema validation failed — %s", path, exc)
        return None


def load_notes(room_name: str, handle: str) -> str:
    room_dir = get_room_dir(room_name)
    result = read_memory(room_dir, f"agents/{handle}/notes")
    if result is None:
        return ""
    _, content = result
    return content


# ── Agent-context (room plan) injection ──────────────────────────────────────
# GET /api/rooms/{room}/agent-context is read on every dispatch, so it's cached
# per-room. The staleness line baked into the rendered block tells the agent
# how old the snapshot is, so a cache hit is still honest.
_AGENT_CONTEXT_TTL_S = 60.0
# room -> (fetched_monotonic, context_or_none, generated_at_iso)
_agent_context_cache: dict[str, tuple[float, str | None, str]] = {}


async def _fetch_agent_context(api_url: str, room_name: str, handle: str) -> tuple[str | None, str]:
    """Return ``(context, generated_at_iso)`` for a room, cached for the TTL.

    Best-effort: a fetch failure never blocks a dispatch. On error a stale
    cache entry is reused if present, else ``(None, "")`` (block omitted).
    """
    now = time.monotonic()
    cached = _agent_context_cache.get(room_name)
    if cached is not None and now - cached[0] < _AGENT_CONTEXT_TTL_S:
        return cached[1], cached[2]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{api_url}/api/rooms/{room_name}/agent-context",
                params={"handle": handle},
            )
            resp.raise_for_status()
            data = resp.json()
        entry = (now, data.get("context"), data.get("generated_at") or "")
        _agent_context_cache[room_name] = entry
        return entry[1], entry[2]
    except Exception as exc:
        log.debug("agent-context fetch failed for %s: %s", room_name, exc)
        if cached is not None:
            return cached[1], cached[2]
        return None, ""


def _humanize_age(generated_at_iso: str) -> str:
    """Render ' (as of HH:MM UTC, ~N min ago)' from an ISO-8601 timestamp."""
    if not generated_at_iso:
        return ""
    try:
        ts = datetime.fromisoformat(generated_at_iso)
    except ValueError:
        return ""
    age_s = max(0.0, (datetime.now(UTC) - ts).total_seconds())
    mins = int(age_s // 60)
    when = ts.strftime("%H:%M UTC")
    if mins < 1:
        return f" (as of {when}, just now)"
    return f" (as of {when}, ~{mins} min ago)"


def _render_plan_block(context: str | None, generated_at_iso: str) -> str:
    """Format the agent-context string into a system-prompt section.

    Returns '' when the room has no plan — callers omit the section entirely.
    """
    if not context:
        return ""
    return (
        f"\n## Room plan{_humanize_age(generated_at_iso)}\n\n{context}\n\n"
        "This snapshot may be stale — run `mycelium plan tasks` for live state.\n"
    )


# ── Gating: allow_from, budget, depth ────────────────────────────────────────


def _normalize_sender(sender_handle: str) -> str:
    return sender_handle.lstrip("@").lower()


def gate_allow_from(manifest: AgentManifest, sender_handle: str) -> bool:
    if not manifest.allow_from:
        return True
    sender = _normalize_sender(sender_handle)
    return any(_normalize_sender(a) == sender for a in manifest.allow_from)


def gate_budget(state: DaemonState, manifest: AgentManifest) -> bool:
    if manifest.budget_usd_per_month <= 0:
        return True
    ym = datetime.now(UTC).strftime("%Y-%m")
    used = state.budget_used_usd.get((manifest.handle, ym), 0.0)
    return used < manifest.budget_usd_per_month


def gate_depth(state: DaemonState, sender_handle: str, depth_cap: int) -> bool:
    """Refuse if *sender_handle* has triggered more than ``depth_cap`` dispatches
    in the trailing 60s window. Approximates a chain-depth cap without needing
    per-message origin chains on the backend."""
    sender = _normalize_sender(sender_handle)
    bucket = state.recent_dispatches[sender]
    now = time.monotonic()
    while bucket and now - bucket[0] > _DEPTH_WINDOW_S:
        bucket.popleft()
    return len(bucket) < depth_cap


# ── claude -p spawn (relocated to integrations/claude_code/spawn.py) ─────────
#
# The body of spawn_claude / _parse_claude_output moved into
# ``mycelium.integrations.claude_code.spawn`` so the daemon dispatch loop can
# call ``integration.spawn(...)`` uniformly across cold-spawn families. The
# next milestone (daemon-core) replaces the hard-coded ``spawn_claude(...)``
# call site below with ``get_integration(manifest.adapter).spawn(...)``.


# ── Side effects: log to memory + reply to room ──────────────────────────────


async def _post_log(
    config: MyceliumConfig,  # noqa: ARG001 — signature kept for symmetry
    room_name: str,
    manifest: AgentManifest,
    *,
    prompt: str,
    sender_handle: str,
    result: SpawnResult,
) -> None:
    """Write the invocation transcript to a daemon-private log directory.

    Logs live OUTSIDE the room's memory namespace (``~/.mycelium/daemon/
    logs/<room>/<handle>/<ts>.json``) so they don't flood the semantic
    index, `memory ls` output, or synthesis runs. `mycelium agent show`
    reads from here. Logs are local-only — they don't sync via git or the
    backend.
    """
    from mycelium.daemon.config import daemon_invocation_log_dir

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    body: dict[str, Any] = {
        "ts": timestamp,
        "room": room_name,
        "handle": manifest.handle,
        "prompt": prompt,
        "sender": sender_handle,
        "ok": result.ok,
        "duration_s": round(result.duration_s, 2),
        "cost_usd": round(result.cost_usd, 4),
        "final_message": result.final_message,
        "transcript": result.transcript[:16_000],
    }
    if result.extra:
        # Family-specific fields (e.g. claude's rate_limit_event); preserved
        # verbatim under a stable key so log analyzers can opt in.
        body["extra"] = result.extra

    def _do() -> None:
        log_dir = daemon_invocation_log_dir(room_name, manifest.handle)
        path = log_dir / f"{timestamp}.json"
        path.write_text(json.dumps(body, indent=2, default=str))

    await asyncio.to_thread(_do)


async def _post_reply(
    config: MyceliumConfig,
    room_name: str,
    manifest: AgentManifest,
    *,
    reply: str,
) -> None:
    """Post the agent's reply back to the originating room as @handle."""
    from mycelium_backend_client import Client
    from mycelium_backend_client.api.messages import (
        send_message_api_rooms_room_name_messages_post as send_api,
    )
    from mycelium_backend_client.models import MessageCreate

    def _do() -> None:
        with Client(base_url=config.server.api_url, raise_on_unexpected_status=True) as client:
            body = MessageCreate(
                sender_handle=manifest.handle,
                message_type="broadcast",
                content=reply,
            )
            send_api.sync(room_name=room_name, client=client, body=body)

    await asyncio.to_thread(_do)


# ── Per-message dispatch ─────────────────────────────────────────────────────


# CognitiveEngine emits ``coordination_tick`` and ``coordination_consensus``
# messages addressed to specific participants in a session sub-room. The
# openclaw plugin handles these via ``routeTick`` / ``routeConsensus`` in
# ``integrations/openclaw/.../channel/route.ts``; cold-spawn families need the
# equivalent so cursor / claude_code agents autonomously invoke
# ``mycelium negotiate respond accept`` etc. instead of waiting for an
# operator-driven accept loop. The two helpers below port
# ``formatTickInstruction`` and ``formatConsensusSummary`` faithfully so the
# prompt the agent sees is identical regardless of family.


def _format_tick_instruction(
    tick_data: dict[str, Any],
    room_name: str,
    target_handle: str,
) -> str:
    """Render a ``coordination_tick`` payload as a self-contained agent prompt.

    Mirrors ``formatTickInstruction`` in the openclaw plugin (see
    ``route.ts``). Surfaces the round header, current offer, valid keys (when
    counter-proposing), shared context files, the parent-room plan tasks, and
    the exact ``mycelium negotiate ...`` commands the agent should invoke.
    Walking away with no agreement is explicitly named as a legitimate
    outcome so an agent with hard constraints doesn't feel pressured to
    accept.
    """
    error_kind = tick_data.get("error") if isinstance(tick_data.get("error"), str) else None
    if error_kind:
        return _format_error_tick(tick_data, room_name, target_handle)

    payload_raw = tick_data.get("payload")
    payload: dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else tick_data
    if not isinstance(payload, dict):
        payload = {}

    action = payload.get("action") or "respond"
    can_counter = payload.get("can_counter_offer") is True
    current_offer_raw = payload.get("current_offer")
    current_offer: dict[str, Any] = current_offer_raw if isinstance(current_offer_raw, dict) else {}
    round_no = payload.get("round", "?")
    n_steps_total = payload.get("n_steps_total")
    your_last_action = payload.get("your_last_action")
    prior_outcome = payload.get("prior_round_outcome")

    offer_keys = list(current_offer.keys())
    offer_summary = "\n".join(f"  {k}: {v}" for k, v in current_offer.items())

    if isinstance(n_steps_total, int) and n_steps_total > 0:
        round_header = f"[CognitiveEngine — Round {round_no} of {n_steps_total}]"
    else:
        round_header = f"[CognitiveEngine — Round {round_no}]"

    context_lines: list[str] = []
    if prior_outcome and prior_outcome != "first_round":
        if isinstance(prior_outcome, str) and prior_outcome.startswith("rejected_by_"):
            who = prior_outcome.removeprefix("rejected_by_")
            context_lines.append(f"Last round: {who} rejected the standing offer.")
        elif prior_outcome == "proposer_countered":
            context_lines.append(
                "Last round: the designated proposer countered with a new offer (shown below)."
            )
        elif prior_outcome == "agreed":
            context_lines.append("Last round: all agents accepted.")
        else:
            context_lines.append(f"Last round: {str(prior_outcome).replace('_', ' ')}.")
    if your_last_action:
        context_lines.append(f"Your last action: {your_last_action}.")

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
            context_files_block.append(content)
            context_files_block.append("--- end ---")

    plan_open_tasks = payload.get("plan_open_tasks")
    plan_block: list[str] = []
    if isinstance(plan_open_tasks, str) and plan_open_tasks:
        plan_block.append(plan_open_tasks)

    valid_keys_line = (
        "Valid offer keys (use exactly these in your counter): "
        + ", ".join(f'"{k}"' for k in offer_keys)
        if can_counter and offer_keys
        else ""
    )

    lines: list[str] = [
        round_header,
        f"You are in a structured negotiation in room {room_name}.",
        f"Action required: {action}",
        "You CAN propose a counter-offer." if can_counter else "You can only accept or reject.",
        "",
        "IMPORTANT: You MUST respond by running one of the `mycelium negotiate` shell",
        "commands listed below. Do NOT post messages to the room directly, do NOT",
        "compose JSON payloads yourself, and do NOT use any other tool to respond.",
        "The ONLY valid way to act is to execute the exact shell command.",
    ]
    if context_lines:
        lines.append("")
        lines.extend(context_lines)
    if context_files_block:
        lines.append("")
        lines.extend(context_files_block)
    if plan_block:
        lines.append("")
        lines.extend(plan_block)
    lines.append("")
    lines.append("Current offer on the table:")
    lines.append(offer_summary)
    lines.append("")
    if valid_keys_line:
        lines.append(valid_keys_line)
    if can_counter:
        lines.append(
            "To counter-propose, run this shell command (pick values from issue_options above):"
        )
        if offer_keys:
            example_pairs = " ".join(
                f'"{k}={current_offer.get(k, "YOUR_CHOICE")}"' for k in offer_keys[:3]
            )
            if len(offer_keys) > 3:
                example_pairs += " ..."
            lines.append(
                f"  mycelium negotiate propose {example_pairs} "
                f"--room {room_name} --handle {target_handle}"
            )
        else:
            lines.append(
                f"  mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... "
                f"--room {room_name} --handle {target_handle}"
            )
        lines.append(
            '  (Each pair is quoted as "key=value". Use the EXACT issue keys shown above.)'
        )
        lines.append(
            '  Do NOT compose JSON or post {"offer": ...} — that format is NOT recognized.'
        )
    lines.append(
        f"To accept: mycelium negotiate respond accept --room {room_name} --handle {target_handle}"
    )
    lines.append(
        f"To reject: mycelium negotiate respond reject --room {room_name} --handle {target_handle}"
    )
    lines.append("")
    lines.append(
        "Explain your reasoning before running the command. Walking away with no agreement is "
        "a legitimate outcome — keep rejecting until the session ends if your hard constraints "
        "can't be met."
    )
    lines.append("")
    lines.append(
        "REMINDER: Run EXACTLY ONE of the shell commands above. Do not post messages, "
        "send JSON, or use any other mechanism. Your ONLY output that matters is the "
        "`mycelium negotiate ...` command execution."
    )
    return "\n".join(lines)


def _format_error_tick(
    tick_data: dict[str, Any],
    room_name: str,
    target_handle: str,
) -> str:
    """Render an error-shaped tick (e.g. ``counter_offer_invalid_keys``).

    The backend posts these as ``coordination_tick`` messages with top-level
    ``error`` / ``instruction`` / ``valid_keys`` / ``bad_keys`` fields. The
    agent needs all of it (especially ``valid_keys``) to recover, so we
    surface it explicitly with a concrete recovery command.
    """
    error_kind = str(tick_data.get("error") or "unknown_error")
    instruction = str(tick_data.get("instruction") or "")
    valid_keys_raw = tick_data.get("valid_keys")
    valid_keys: list[Any] = valid_keys_raw if isinstance(valid_keys_raw, list) else []
    bad_keys_raw = tick_data.get("bad_keys")
    bad_keys: list[Any] = bad_keys_raw if isinstance(bad_keys_raw, list) else []

    lines: list[str] = [
        f"[CognitiveEngine — error: {error_kind}]",
        f"Room: {room_name}",
    ]
    if instruction:
        lines.append("")
        lines.append(instruction)
    if bad_keys:
        lines.append("")
        lines.append("Rejected keys: " + ", ".join(f'"{k}"' for k in bad_keys))
    if valid_keys:
        lines.append("")
        lines.append("Valid keys (use exactly these): " + ", ".join(f'"{k}"' for k in valid_keys))
    if error_kind == "counter_offer_invalid_keys" and valid_keys:
        example = " ".join(f'"{k}"=VALUE' for k in valid_keys)
        lines.append("")
        lines.append(
            f"Recovery: mycelium negotiate propose {example} "
            f"--room {room_name} --handle {target_handle}"
        )
    elif error_kind == "counter_offer_not_your_turn":
        lines.append("")
        lines.append(
            f"Recovery: mycelium negotiate respond accept "
            f"--room {room_name} --handle {target_handle}"
        )
        lines.append(
            f"      or: mycelium negotiate respond reject "
            f"--room {room_name} --handle {target_handle}"
        )
    return "\n".join(lines)


def _format_consensus_summary(consensus_data: dict[str, Any]) -> str:
    """Render a ``coordination_consensus`` payload as an agent prompt.

    Mirrors ``formatConsensusSummary`` in the openclaw plugin. On success,
    surfaces the plan, per-agent assignments, and the ``plan_file`` pointer
    so the agent can flow straight into doing the work. On a broken
    negotiation, reports the failure plainly with the available context.
    """
    plan = consensus_data.get("plan") or "No plan details"
    assignments_raw = consensus_data.get("assignments")
    assignments: dict[str, Any] = assignments_raw if isinstance(assignments_raw, dict) else {}
    broken = consensus_data.get("broken") is True
    plan_file_raw = consensus_data.get("plan_file")
    plan_file = plan_file_raw if isinstance(plan_file_raw, str) else ""

    if broken:
        return f"[CognitiveEngine — Negotiation FAILED]\n{plan}"

    plan_text = plan if isinstance(plan, str) else json.dumps(plan, indent=2)
    lines: list[str] = [
        "[CognitiveEngine — Consensus Reached!]",
        "",
        plan_text,
        "",
        "Assignments:",
    ]
    lines.extend(f"  {agent}: {task}" for agent, task in assignments.items())
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


async def on_message(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room_name: str,
    msg: dict[str, Any],
) -> None:
    """Inspect *msg* and dispatch if it @-mentions an agent we host."""
    msg_id = str(msg.get("id") or "")
    if msg_id:
        if msg_id in state.seen_message_ids:
            return
        state.seen_message_ids.append(msg_id)

    message_type = str(msg.get("message_type") or "broadcast")
    if message_type == "coordination_tick":
        await _handle_tick(
            config=config,
            daemon_cfg=daemon_cfg,
            state=state,
            room_name=room_name,
            msg=msg,
        )
        return
    if message_type == "coordination_consensus":
        await _handle_consensus(
            config=config,
            daemon_cfg=daemon_cfg,
            state=state,
            room_name=room_name,
            msg=msg,
        )
        return
    if message_type == "room_deleted":
        await _handle_room_deleted(
            room_name=room_name,
            config=config,
            state=state,
        )
        return
    if message_type in {"coordination_join", "coordination_start"}:
        # Discover session sub-rooms — ticks live there, not in the parent
        # room. Mirrors the openclaw plugin's ``subscribe-session`` action.
        await _handle_join(
            config=config,
            daemon_cfg=daemon_cfg,
            state=state,
            msg=msg,
        )
        return

    content = str(msg.get("content") or "")
    sender_handle = str(msg.get("sender_handle") or "")
    if not content:
        return

    handles = list_agent_handles(room_name)
    if not handles:
        return

    mentioned = resolve_mentions(content, handles)
    if not mentioned:
        return

    # Skip self-mentions to avoid trivial loops.
    sender_norm = _normalize_sender(sender_handle)
    mentioned = [h for h in mentioned if _normalize_sender(h) != sender_norm]
    if not mentioned:
        return

    for handle in mentioned:
        manifest = load_manifest(room_name, handle)
        if manifest is None:
            log.warning("no manifest for @%s in %s", handle, room_name)
            continue
        # Skip families this daemon doesn't dispatch (e.g. openclaw — its own
        # gateway delivers mentions). The registry is the one source of truth
        # for which families are cold_spawn vs long_lived_gateway; no more
        # ``if manifest.adapter == "..."`` branching here.
        try:
            integration = get_integration(manifest.adapter)
        except ValueError:
            log.warning(
                "unknown adapter %r on @%s in %s — skipping",
                manifest.adapter,
                handle,
                room_name,
            )
            continue
        if integration.lifecycle != "cold_spawn":
            log.debug(
                "skip @%s — adapter=%s lifecycle=%s (owned by external runtime)",
                handle,
                manifest.adapter,
                integration.lifecycle,
            )
            continue
        if handle not in daemon_cfg.handles:
            # A claude_code manifest can reach this machine's filesystem via
            # room sync, but the agent runs on whichever machine created it.
            # Ownership is recorded in daemon.toml by `mycelium agent
            # create`; without that, two daemons subscribed to one room would
            # both dispatch — and both spawn `claude` in the manifest's cwd.
            log.debug("skip @%s — not owned by this daemon", handle)
            continue

        if not gate_allow_from(manifest, sender_handle):
            log.info("denied @%s ← %s (allow_from)", handle, sender_handle)
            continue

        # Control verbs run OUTSIDE the per-handle lock so they can act on a
        # running spawn (abort) or answer instantly while one is in flight
        # (status). They're also exempt from budget + depth caps — they
        # don't spend money and don't kick the chain forward.
        body = _extract_body(content, handle)
        verb = _leading_verb(body)
        if verb in _CONTROL_ABORT:
            asyncio.create_task(
                _handle_abort(
                    config=config,
                    state=state,
                    room_name=room_name,
                    manifest=manifest,
                    sender_handle=sender_handle,
                )
            )
            continue
        if verb in _CONTROL_STATUS:
            asyncio.create_task(
                _handle_status(
                    config=config,
                    state=state,
                    room_name=room_name,
                    manifest=manifest,
                )
            )
            continue

        if not gate_budget(state, manifest):
            log.warning("denied @%s (budget exceeded)", handle)
            continue
        if not gate_depth(state, sender_handle, daemon_cfg.depth_cap):
            log.warning(
                "denied @%s ← %s (depth cap %d in 60s)",
                handle,
                sender_handle,
                daemon_cfg.depth_cap,
            )
            continue

        asyncio.create_task(
            _dispatch_one(
                config=config,
                daemon_cfg=daemon_cfg,
                state=state,
                room_name=room_name,
                manifest=manifest,
                sender_handle=sender_handle,
                prompt=content,
            )
        )


# ── Control verbs ────────────────────────────────────────────────────────────


async def _handle_tick(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room_name: str,
    msg: dict[str, Any],
) -> None:
    """Cold-spawn the addressed participant in response to a CFN tick.

    The CognitiveEngine targets one agent per tick via
    ``payload.participant_id``. We mirror the openclaw plugin's ``routeTick``:
    parse the tick JSON, format a complete instruction (round / current
    offer / valid keys / accept-or-reject CLI commands), and dispatch the
    owned handle through the same ``_dispatch_one`` path as a normal
    @-mention so the agent autonomously runs ``mycelium negotiate respond``.
    Without this branch every cold-spawn family would fall back to
    operator-driven accept loops, which is the gap that surfaced in the
    cursor-e2e Phase 5 walkthrough.
    """
    raw = str(msg.get("content") or "")
    if not raw:
        return
    try:
        tick_data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("coordination_tick in %s: unparseable JSON content", room_name)
        return
    if not isinstance(tick_data, dict):
        return

    payload = tick_data.get("payload") if isinstance(tick_data.get("payload"), dict) else tick_data
    target_handle = payload.get("participant_id") if isinstance(payload, dict) else None
    if not isinstance(target_handle, str) or not target_handle:
        log.debug("coordination_tick in %s: missing participant_id", room_name)
        return

    if target_handle not in daemon_cfg.handles:
        # Sibling daemons share the SSE stream — only the owning daemon
        # spawns. Without this guard, two daemons would both cold-spawn the
        # same handle and race on the workspace.
        log.debug(
            "skip tick → @%s in %s — not owned by this daemon",
            target_handle,
            room_name,
        )
        return

    # Ticks always arrive in a session sub-room (``parent:session:<id>``)
    # because that's the only channel CognitiveEngine NOTIFY's on. Manifests
    # are mirrored under the *parent* room, so derive that for the lookup —
    # otherwise every tick lands as "no manifest in local mirror" even
    # though the agent is registered correctly.
    parent_room = room_name.split(":session:", 1)[0] if ":session:" in room_name else room_name
    manifest = load_manifest(parent_room, target_handle)
    if manifest is None:
        log.warning(
            "coordination_tick @%s in %s: no manifest in local mirror (parent=%s) — skipping",
            target_handle,
            room_name,
            parent_room,
        )
        return

    try:
        integration = get_integration(manifest.adapter)
    except ValueError:
        log.warning(
            "coordination_tick @%s: unknown adapter %r — skipping",
            target_handle,
            manifest.adapter,
        )
        return
    if integration.lifecycle != "cold_spawn":
        # ``long_lived_gateway`` families (openclaw, hermes) handle ticks in
        # their own runtime; cold-spawn families are the daemon's responsibility.
        log.debug(
            "skip tick → @%s — adapter=%s lifecycle=%s",
            target_handle,
            manifest.adapter,
            integration.lifecycle,
        )
        return

    if not gate_budget(state, manifest):
        log.warning("denied tick → @%s (budget exceeded)", target_handle)
        return
    # Ticks are server-driven, not chained by another agent's reply, so the
    # depth cap doesn't apply here. ``allow_from`` is also bypassed: the
    # CognitiveEngine is the trusted protocol partner, not a peer agent.

    instruction = _format_tick_instruction(tick_data, room_name, target_handle)
    log.info(
        "coordination_tick @%s in %s — round=%s action=%s",
        target_handle,
        room_name,
        (tick_data.get("payload") or {}).get("round")
        if isinstance(tick_data.get("payload"), dict)
        else tick_data.get("round"),
        (tick_data.get("payload") or {}).get("action")
        if isinstance(tick_data.get("payload"), dict)
        else tick_data.get("action"),
    )
    asyncio.create_task(
        _dispatch_one(
            config=config,
            daemon_cfg=daemon_cfg,
            state=state,
            room_name=room_name,
            manifest=manifest,
            sender_handle=_CFN_SENDER,
            prompt=instruction,
        )
    )


async def _handle_consensus(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room_name: str,
    msg: dict[str, Any],
) -> None:
    """Cold-spawn every owned handle in *room_name* with the consensus summary.

    Mirrors ``routeConsensus`` in the openclaw plugin: every agent that
    participated in the negotiation (or could have) sees the final plan and
    assignments, so the negotiation flows straight into doing the work
    rather than a silent ``type=consensus`` event the agent never observes.
    """
    raw = str(msg.get("content") or "")
    if not raw:
        return
    try:
        consensus_data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("coordination_consensus in %s: unparseable JSON content", room_name)
        return
    if not isinstance(consensus_data, dict):
        return

    summary = _format_consensus_summary(consensus_data)
    # Ticks/consensus arrive in the session sub-room; agent manifests live
    # under the parent room. Look up handles + manifests there, but keep
    # ``room_name`` (the sub-room) for the spawn so the agent's reply lands
    # back in the session, not the parent room.
    parent_room = room_name.split(":session:", 1)[0] if ":session:" in room_name else room_name
    handles = list_agent_handles(parent_room)
    for handle in handles:
        if handle not in daemon_cfg.handles:
            continue
        manifest = load_manifest(parent_room, handle)
        if manifest is None:
            continue
        try:
            integration = get_integration(manifest.adapter)
        except ValueError:
            continue
        if integration.lifecycle != "cold_spawn":
            continue
        if not gate_budget(state, manifest):
            log.warning("denied consensus → @%s (budget exceeded)", handle)
            continue
        log.info("coordination_consensus → @%s in %s", handle, room_name)
        asyncio.create_task(
            _dispatch_one(
                config=config,
                daemon_cfg=daemon_cfg,
                state=state,
                room_name=room_name,
                manifest=manifest,
                sender_handle=_CFN_SENDER,
                prompt=summary,
            )
        )


async def _handle_join(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    msg: dict[str, Any],
) -> None:
    """Dynamically subscribe to a session sub-room when an agent joins it.

    CognitiveEngine posts ticks/consensus into ``r:session:abc`` sub-rooms,
    not the parent room. The daemon's static SSE subscriptions (from
    ``daemon.toml``) only cover parent rooms, so without this branch the
    daemon would observe the join + nothing else and fall back to the
    operator-driven accept loop. We mirror the openclaw plugin's
    ``subscribe-session`` action: discover the sub-room, fire a ``subscribe_room``
    task, and rely on the idempotent task map so duplicate joins (or
    coordination_start events) don't create competing listeners.

    Discovery sources, in priority order:
      - ``msg.room_name`` — already a session sub-room (e.g. when this is a
        join echo from inside the sub-room itself)
      - ``content.session`` — the session pointer the engine attaches to
        every coordination_join broadcast in the parent room
    """
    room_name = msg.get("room_name") if isinstance(msg.get("room_name"), str) else ""
    target: str | None = None
    if isinstance(room_name, str) and ":session:" in room_name:
        target = room_name
    else:
        raw = str(msg.get("content") or "")
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                session = data.get("session")
                if isinstance(session, str) and ":session:" in session:
                    target = session

    if not target:
        return
    if target in state.session_room_tasks:
        return

    log.info("dynamic subscribe → %s (session sub-room)", target)
    task = asyncio.create_task(
        subscribe_room(
            config=config,
            daemon_cfg=daemon_cfg,
            state=state,
            room_name=target,
        ),
        name=f"sse[{target}]",
    )
    state.session_room_tasks[target] = task


async def _handle_abort(
    *,
    config: MyceliumConfig,
    state: DaemonState,
    room_name: str,
    manifest: AgentManifest,
    sender_handle: str,
) -> None:
    """`@handle abort|cancel|stop` — SIGTERM the agent's running spawn."""
    running = state.running.get(manifest.handle)
    if running is None:
        await _post_reply(
            config,
            room_name,
            manifest,
            reply=f"○ nothing to abort (no run in flight) — {sender_handle}",
        )
        return
    try:
        running.process.terminate()
    except ProcessLookupError:
        pass
    log.info(
        "abort @%s ← %s (running %.1fs)",
        manifest.handle,
        sender_handle,
        time.monotonic() - running.started_at,
    )
    await _post_reply(
        config,
        room_name,
        manifest,
        reply=f"✗ aborted by {sender_handle}",
    )


async def _handle_status(
    *,
    config: MyceliumConfig,
    state: DaemonState,
    room_name: str,
    manifest: AgentManifest,
) -> None:
    """`@handle status` — describe the agent's current state."""
    running = state.running.get(manifest.handle)
    if running is not None:
        elapsed = time.monotonic() - running.started_at
        reply = (
            f"● running for {elapsed:.0f}s (prompt: {running.prompt[:80]!r}, from {running.sender})"
        )
    else:
        last = state.last_dispatch or {}
        if last.get("agent") == manifest.handle:
            reply = (
                f"○ idle · last run: {last.get('result')} in "
                f"{last.get('duration_s', 0):.1f}s (cost ${last.get('cost_usd', 0):.4f})"
            )
        else:
            reply = "○ idle · no recent runs"
    await _post_reply(config, room_name, manifest, reply=reply)


async def _dispatch_one(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room_name: str,
    manifest: AgentManifest,
    sender_handle: str,
    prompt: str,
) -> None:
    """Run a single dispatch under the per-handle serial lock."""
    lock = state.lock_for(manifest.handle)
    async with lock:
        state.recent_dispatches[_normalize_sender(sender_handle)].append(time.monotonic())

        notes = load_notes(room_name, manifest.handle)
        log.info(
            "dispatch @%s ← %s (room=%s, cmd=%s)",
            manifest.handle,
            sender_handle,
            room_name,
            shlex.quote(prompt[:60]),
        )

        body = _extract_body(prompt, manifest.handle) or prompt
        # Room plan briefing — best-effort, cached per-room. The agent sees
        # the room's title + open tasks so its reply is plan-aware.
        ctx, generated_at = await _fetch_agent_context(
            config.server.api_url, room_name, manifest.handle
        )
        # Family-agnostic dispatch: the integration owns the CLI invocation
        # (``claude -p``, ``cursor-agent -p``, future Gemini/Codex/Aider).
        # The dispatch loop only knows it gets a SpawnResult back.
        integration = get_integration(manifest.adapter)
        binary = daemon_cfg.binary_for(manifest.adapter)
        request = SpawnRequest(
            handle=manifest.handle,
            room=room_name,
            # The AgentManifest validator guarantees cold-spawn families have
            # a cwd. The ``or ""`` is a type-safe floor — an empty cwd makes
            # the family's spawn return its clean "cwd is not a directory"
            # error rather than crash.
            cwd=manifest.cwd or "",
            prompt=body,
            description=manifest.description,
            sender=sender_handle,
            notes=notes,
            plan_block=_render_plan_block(ctx, generated_at),
            binary=binary,
            state=state,
        )
        result = await integration.spawn(request=request)

        if result.aborted:
            # Aborted via control verb — the abort handler already posted its
            # own reply, so we just log here and skip the normal log+reply
            # pair. Falling through would post the empty final_message.
            log.info("abort acknowledged for @%s", manifest.handle)
            state.record_dispatch(
                handle=manifest.handle,
                room=room_name,
                result="aborted",
                duration_s=result.duration_s,
                cost_usd=0.0,
            )
            return

        # Track spend in-memory (per-process, per calendar month). Families
        # that don't expose per-call cost (e.g. cursor) return 0.0 here.
        ym = datetime.now(UTC).strftime("%Y-%m")
        state.budget_used_usd[(manifest.handle, ym)] = (
            state.budget_used_usd.get((manifest.handle, ym), 0.0) + result.cost_usd
        )
        state.record_dispatch(
            handle=manifest.handle,
            room=room_name,
            result="ok" if result.ok else "error",
            duration_s=result.duration_s,
            cost_usd=result.cost_usd,
        )

        try:
            await _post_log(
                config,
                room_name,
                manifest,
                prompt=prompt,
                sender_handle=sender_handle,
                result=result,
            )
        except Exception as exc:
            state.record_error("post_log", exc)
            log.warning("could not write log entry for @%s: %s", manifest.handle, exc)

        try:
            await _post_reply(config, room_name, manifest, reply=result.final_message)
        except Exception as exc:
            state.record_error("post_reply", exc)
            log.warning("could not post reply for @%s: %s", manifest.handle, exc)


# ── Coordination-session discovery (poller) ─────────────────────────────────


async def poll_coordination_sessions(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
) -> None:
    """Maintain dynamic SSE subscriptions for every active coordination session.

    The CognitiveEngine emits ticks / consensus into the session sub-room's
    NOTIFY channel, never the parent room's. A daemon subscribed only to
    parent rooms (``daemon.toml`` lists those) would observe a join in
    the database but no live updates afterwards. We solve this the same way
    the openclaw plugin does (``integrations/openclaw/.../channel/index.ts``):
    poll ``/api/coordination-sessions`` every few seconds, subscribe to any
    session in a live state, and tear down subscriptions for sessions that
    have completed (or were deleted). Idempotent on
    ``state.session_room_tasks`` so duplicate poll ticks don't create
    competing listeners.
    """
    url = f"{config.server.api_url}/api/coordination-sessions"
    while not state.stopping.is_set():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params={"limit": _SESSION_POLL_LIMIT})
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            # Polling failure is non-fatal — log once and try again next tick.
            # Without this guard a transient backend hiccup would blow up the
            # whole daemon's coordination discovery.
            log.debug("coordination-sessions poll failed: %s", exc)
            payload = []

        active: set[str] = set()
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                display_name = item.get("display_name")
                session_state = item.get("state")
                if not isinstance(display_name, str) or ":session:" not in display_name:
                    continue
                if session_state not in _SESSION_LIVE_STATES:
                    continue
                active.add(display_name)
                if display_name in state.session_room_tasks:
                    existing = state.session_room_tasks[display_name]
                    if not getattr(existing, "done", lambda: False)():
                        continue
                    # The previous task finished (peer disconnect, server
                    # restart, etc.) but the session is still live —
                    # restart it.
                log.info("dynamic subscribe → %s (coordination session)", display_name)
                state.session_room_tasks[display_name] = asyncio.create_task(
                    subscribe_room(
                        config=config,
                        daemon_cfg=daemon_cfg,
                        state=state,
                        room_name=display_name,
                    ),
                    name=f"sse[{display_name}]",
                )

        # Drop subscriptions for sessions that left the active set so we
        # don't pin SSE connections on completed negotiations forever.
        for tracked in list(state.session_room_tasks.keys()):
            if tracked in active:
                continue
            task = state.session_room_tasks.pop(tracked)
            log.info("dynamic unsubscribe → %s (session no longer active)", tracked)
            task.cancel()

        try:
            await asyncio.wait_for(
                state.stopping.wait(),
                timeout=_SESSION_POLL_INTERVAL_S,
            )
        except TimeoutError:
            continue
        # state.stopping is set — fall through and exit the loop.
        return


# ── Room-deleted handling and startup reconciliation ─────────────────────────


async def _handle_room_deleted(
    *,
    room_name: str,
    config: MyceliumConfig,
    state: DaemonState,
) -> None:
    """React to a ``room_deleted`` SSE tombstone from the hub.

    Called while the SSE connection is still live (the tombstone fires before
    the DB row is removed).  Cleans up all local spoke state immediately so
    agents don't receive stale ticks from a room that no longer exists.

    Actions (all non-fatal individually):
      1. Mark the room as deleted so ``subscribe_room`` exits its loop.
      2. Remove the local ``~/.mycelium/rooms/<room>/`` directory if
         ``daemon.auto_gc_orphaned_rooms`` is enabled; otherwise just warn.
      3. Unregister the room from openclaw and hermes adapter configs so
         their plugins stop opening SSE connections to a dead room.
    """
    import shutil

    log.info("room_deleted received for '%s' — cleaning up local state", room_name)
    state.rooms_deleted.add(room_name)

    # Build the room path directly to avoid get_room_dir()'s implicit mkdir,
    # which would recreate the directory we're trying to report as orphaned.
    from mycelium.filesystem import get_mycelium_dir

    room_dir = get_mycelium_dir() / "rooms" / room_name

    if config.daemon.auto_gc_orphaned_rooms:
        if room_dir.exists():
            try:
                shutil.rmtree(room_dir)
                log.info("Removed local room directory: %s", room_dir)
            except Exception as exc:
                log.warning("Failed to remove local room directory %s: %s", room_dir, exc)
    else:
        if room_dir.exists():
            log.warning(
                "Room '%s' deleted from the backend — local directory left at %s "
                "(set daemon.auto_gc_orphaned_rooms=true or run 'mycelium room gc')",
                room_name,
                room_dir,
            )

    # Trigger hot-reload immediately — _reconcile_rooms filters state.rooms_deleted
    # from desired, so the SSE task is cleaned up even if the config update below
    # fails (e.g. disk-full on save()).
    state.reload_requested.set()

    # Best-effort: remove from daemon.toml so the room is not re-subscribed on
    # next daemon restart.
    try:
        from mycelium.daemon.config import DaemonConfig

        daemon_cfg = DaemonConfig.load()
        if room_name in daemon_cfg.rooms:
            daemon_cfg.rooms.remove(room_name)
            try:
                daemon_cfg.save()
                log.info("Removed '%s' from daemon subscription list", room_name)
            except Exception as save_exc:
                log.warning(
                    "Could not save daemon config after removing '%s': %s", room_name, save_exc
                )
    except Exception as exc:
        log.warning("Could not load daemon config for deleted room '%s': %s", room_name, exc)

    try:
        from mycelium.integrations.openclaw.dispatch import unregister_room_from_openclaw

        removed = unregister_room_from_openclaw(room_name)
        if removed:
            log.info(
                "Unregistered %d openclaw agent(s) from deleted room '%s'",
                len(removed),
                room_name,
            )
    except Exception as exc:
        log.debug("openclaw unregister skipped for '%s': %s", room_name, exc)

    try:
        from mycelium.integrations.hermes.dispatch import unregister_room_from_hermes

        removed = unregister_room_from_hermes(room_name)
        if removed:
            log.info(
                "Unregistered %d hermes agent(s) from deleted room '%s'",
                len(removed),
                room_name,
            )
    except Exception as exc:
        log.debug("hermes unregister skipped for '%s': %s", room_name, exc)


async def reconcile_local_rooms(config: MyceliumConfig) -> None:
    """On daemon startup, verify each local room directory against the hub API.

    A spoke that was offline when a room was deleted on the hub will have
    missed the ``room_deleted`` SSE tombstone.  This pull-based reconciliation
    catches those orphans at next startup.

    Behaviour is gated on ``daemon.auto_gc_orphaned_rooms`` in config.toml:
      - False (default): log a warning and leave cleanup to the operator
        (use ``mycelium doctor`` or ``mycelium room gc``).
      - True: remove the orphaned directory and unregister adapter configs
        automatically.

    A ``ConnectError`` or ``ConnectTimeout`` (hub unreachable) aborts the scan
    immediately — we'd rather leave local state intact than delete rooms because
    the network was down during startup.
    """
    import shutil

    from mycelium.filesystem import get_mycelium_dir

    rooms_root = get_mycelium_dir() / "rooms"
    if not rooms_root.exists():
        return

    api_url = config.server.api_url

    # Load daemon config once; patch it for each orphan found; save once at the
    # end.  This avoids O(n) load/save cycles when many rooms are orphaned.
    from mycelium.daemon.config import DaemonConfig as _DC

    try:
        _dcfg: _DC | None = _DC.load()
    except Exception as exc:
        log.warning("Startup reconcile: could not load daemon config: %s", exc)
        _dcfg = None
    _dcfg_changed = False

    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=10) as client:
            for room_dir in sorted(rooms_root.iterdir()):
                if not room_dir.is_dir():
                    continue
                room_name = room_dir.name
                try:
                    resp = await client.get(f"/api/rooms/{room_name}")
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    # ConnectTimeout is not a subclass of ConnectError; catch both.
                    # Break rather than return so the batched config save still runs
                    # for any orphans already found before the hub became unreachable.
                    log.warning(
                        "Hub unreachable during startup reconcile — skipping remaining rooms"
                    )
                    break
                except Exception as exc:
                    log.debug("Reconcile check failed for '%s': %s", room_name, exc)
                    continue

                if resp.status_code != 404:
                    continue

                # Room is gone on the hub.  Queue removal from daemon_cfg.rooms so
                # the runner does not spawn a 404-retry SSE task on startup.
                # Saved once after this loop ends.
                if _dcfg is not None and room_name in _dcfg.rooms:
                    _dcfg.rooms.remove(room_name)
                    _dcfg_changed = True

                if config.daemon.auto_gc_orphaned_rooms:
                    try:
                        shutil.rmtree(room_dir)
                        log.info(
                            "Startup reconcile: removed orphaned room directory '%s'", room_name
                        )
                    except Exception as exc:
                        log.warning("Startup reconcile: failed to remove '%s': %s", room_dir, exc)
                else:
                    log.warning(
                        "Startup reconcile: room '%s' not registered in the backend — "
                        "orphaned local directory at %s "
                        "(run 'mycelium room gc' or set daemon.auto_gc_orphaned_rooms=true)",
                        room_name,
                        room_dir,
                    )

                # Always unregister adapter configs — the hub has deleted the room
                # regardless of whether we removed the local directory.
                try:
                    from mycelium.integrations.openclaw.dispatch import (
                        unregister_room_from_openclaw,
                    )

                    unregister_room_from_openclaw(room_name)
                except Exception:
                    pass
                try:
                    from mycelium.integrations.hermes.dispatch import (
                        unregister_room_from_hermes,
                    )

                    unregister_room_from_hermes(room_name)
                except Exception:
                    pass
    except Exception as exc:
        log.warning("Startup room reconcile failed: %s", exc)

    if _dcfg is not None and _dcfg_changed:
        try:
            _dcfg.save()
        except Exception as exc:
            log.warning("Startup reconcile: could not save daemon config: %s", exc)


# ── SSE subscription per room ────────────────────────────────────────────────


async def subscribe_room(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room_name: str,
) -> None:
    """Stay connected to *room_name*'s SSE stream until the daemon stops."""
    # A re-created room that was previously deleted will still appear in
    # rooms_deleted.  Clear the tombstone so the subscription loop doesn't
    # exit immediately on the first message.
    state.rooms_deleted.discard(room_name)
    url = f"{config.server.api_url}/api/rooms/{room_name}/messages/stream"

    # No total timeout (the stream is long-lived) but a bounded read timeout
    # so a stalled connection is detected via httpx.ReadTimeout rather than
    # hanging aiter_text() forever. write/pool bounded too; defensive.
    timeout = httpx.Timeout(
        None,
        connect=_SSE_CONNECT_TIMEOUT_S,
        read=_SSE_READ_TIMEOUT_S,
        write=_SSE_CONNECT_TIMEOUT_S,
        pool=_SSE_CONNECT_TIMEOUT_S,
    )

    while not state.stopping.is_set():
        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream("GET", url, headers={"Accept": "text/event-stream"}) as resp,
            ):
                if resp.status_code == 404:
                    log.warning(
                        "SSE 404 for %s — room may not exist; retry in 15s",
                        room_name,
                    )
                    await asyncio.sleep(15)
                    continue
                if resp.status_code >= 400:
                    log.warning("SSE %s for %s — retry in 5s", resp.status_code, room_name)
                    await asyncio.sleep(5)
                    continue

                log.info("SSE connected: %s", room_name)
                state.rooms_connected.add(room_name)

                buffer = ""
                async for chunk in resp.aiter_text():
                    if state.stopping.is_set():
                        break
                    buffer += chunk
                    blocks = buffer.split("\n\n")
                    buffer = blocks.pop()
                    for block in blocks:
                        for line in block.split("\n"):
                            if not line.startswith("data: "):
                                continue
                            raw = line[6:].strip()
                            if not raw or raw == "{}":
                                continue
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            try:
                                await on_message(
                                    config=config,
                                    daemon_cfg=daemon_cfg,
                                    state=state,
                                    room_name=room_name,
                                    msg=msg,
                                )
                            except Exception as exc:
                                state.record_error(f"on_message[{room_name}]", exc)
                                log.exception("dispatch error in %s: %s", room_name, exc)
                            # Exit cleanly if the hub sent a room_deleted tombstone.
                            if room_name in state.rooms_deleted:
                                log.info(
                                    "SSE: room '%s' deleted — closing subscription",
                                    room_name,
                                )
                                return
        except asyncio.CancelledError:
            raise
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            # A stalled/half-open stream: no keep-alive for _SSE_READ_TIMEOUT_S
            # (or the hub didn't accept the connection in time). Distinct log
            # so operators can tell a deaf socket from a network error.
            state.record_error(f"sse_stalled[{room_name}]", exc)
            log.warning(
                "SSE stalled for %s (no data within %.0fs) — reconnecting in 5s",
                room_name,
                _SSE_READ_TIMEOUT_S,
            )
        except Exception as exc:
            state.record_error(f"sse[{room_name}]", exc)
            log.warning("SSE error for %s: %s — retry in 5s", room_name, exc)
        finally:
            state.rooms_connected.discard(room_name)

        if state.stopping.is_set():
            return
        await asyncio.sleep(5)
