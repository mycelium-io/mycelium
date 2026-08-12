# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""@handle dispatch logic — the heart of the daemon.

No transport of its own: this module is the @-mention dispatch logic (tick /
consensus / mention handling and their pure helpers) reused by the SLIM
connector (``connector.py``), which owns the wire. The legacy httpx SSE
subscription and coordination-session poller that once drove this module were
retired once agents moved to SLIM.
"""

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


# Reserved verbs at the start of an addressed message body. Anything not in
# this set goes through to claude -p as a normal prompt.
_CONTROL_ABORT = {"abort", "cancel", "stop"}
_CONTROL_STATUS = {"status"}

# The aligner (the mediator engine) is the trusted sender for the tick /
# consensus messages that drive a negotiation. We attribute autonomous spawns to
# it so logs and depth-buckets distinguish mediator-driven dispatches from
# agent-driven @-mentions.
_ALIGNER_SENDER = "aligner"


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


# The aligner emits ``coordination_tick`` and ``coordination_consensus``
# messages addressed to specific participants in a session sub-room. Cold-spawn
# families render these into a prompt so cursor / claude_code agents
# autonomously invoke ``mycelium negotiate respond accept`` etc. instead of
# waiting for an operator-driven accept loop. The two helpers below format the
# tick and consensus payloads so the prompt the agent sees is identical
# regardless of family.


def _format_tick_instruction(
    tick_data: dict[str, Any],
    room_name: str,
    target_handle: str,
) -> str:
    """Render a ``coordination_tick`` payload as a self-contained agent prompt.

    Surfaces the round header, current offer, valid keys (when
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
        round_header = f"[aligner: Round {round_no} of {n_steps_total}]"
    else:
        round_header = f"[aligner: Round {round_no}]"

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
        f"[aligner: error: {error_kind}]",
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

    On success,
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
        return f"[aligner: Negotiation FAILED]\n{plan}"

    plan_text = plan if isinstance(plan, str) else json.dumps(plan, indent=2)
    lines: list[str] = [
        "[aligner: Consensus Reached!]",
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
        # Skip families this daemon doesn't dispatch (e.g. a long-lived
        # gateway family delivers its own mentions). The registry is the one
        # source of truth for which families are cold_spawn vs
        # long_lived_gateway; no more ``if manifest.adapter == "..."`` here.
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

    The aligner targets one agent per tick via
    ``payload.participant_id``. We
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
    # because that's the only channel the aligner NOTIFY's on. Manifests
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
        # ``long_lived_gateway`` families handle ticks in their own runtime;
        # cold-spawn families are the daemon's responsibility.
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
    # The aligner is the trusted protocol partner, not a peer agent.

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
            sender_handle=_ALIGNER_SENDER,
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

    Every agent that
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
                sender_handle=_ALIGNER_SENDER,
                prompt=summary,
            )
        )


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
