"""Coordination helpers for SLIM-native Mycelium.

SLIM-native flow (correct order):
  1. Create agents in room via CLI.
  2. Each agent posts an opening position via ``mycelium respond``.
  3. Agents start ``mycelium await`` loops — this generates coordination_join
     messages, making them "present" to the aligner roster.
  4. Create + invoke the aligner engine.  Aligner sees: agents present + opening
     positions → starts coordination rounds.
  5. Aligner sends coordination_tick to each agent.
  6. Agents ``mycelium respond`` per turn with accept/reject/counter.
  7. Aligner commits via an ``l9_commit`` room message:
       subkind=converged → consensus reached
       subkind=rejected  → could not converge (timeout, intractable, etc.)

Terminal detection: poll room messages for ``l9_commit``.
The ``/api/rooms/{room}/sessions`` endpoint tracks a different primitive
(in-progress session participants), not historical coordination outcomes.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI

log = logging.getLogger(__name__)

# l9_commit subkinds
SUBKIND_CONVERGED = "converged"
SUBKIND_REJECTED = "rejected"
TERMINAL_SUBKINDS = frozenset({SUBKIND_CONVERGED, SUBKIND_REJECTED})


# ── Message scanning ──────────────────────────────────────────────────────────


def _parse_l9_commit(message: dict) -> dict[str, Any] | None:
    """Return the parsed l9_commit payload if *message* is a terminal commit."""
    if message.get("message_type") != "l9_commit":
        return None
    content = message.get("content") or "{}"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = {"raw": content}
    l9 = payload.get("l9", {})
    subkind = l9.get("header", {}).get("subkind", "")
    return payload if subkind in TERMINAL_SUBKINDS else None


def scan_for_terminal(messages: list[dict]) -> dict[str, Any] | None:
    """Return the first terminal l9_commit payload found in *messages*, or None."""
    for m in messages:
        commit = _parse_l9_commit(m)
        if commit is not None:
            return commit
    return None


def is_converged(commit_payload: dict) -> bool:
    subkind = commit_payload.get("l9", {}).get("header", {}).get("subkind", "")
    return subkind == SUBKIND_CONVERGED


def wait_for_coordination_join(
    api: MyceliumAPI,
    room: str,
    expected_handles: list[str],
    timeout: int = 15,
    poll_interval: float = 1.0,
) -> bool:
    """Poll room messages until all *expected_handles* have posted coordination_join."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, msgs = api.get_room_messages(room, limit=50)
        if isinstance(msgs, list):
            joined = {
                m.get("content", "{}")
                for m in msgs
                if m.get("message_type") == "coordination_join"
            }
            joined_handles = set()
            for content in joined:
                try:
                    joined_handles.add(json.loads(content).get("handle", ""))
                except json.JSONDecodeError:
                    pass
            if all(h in joined_handles for h in expected_handles):
                log.info("All agents joined: %s", expected_handles)
                return True
        time.sleep(poll_interval)
    missing = [h for h in expected_handles if h not in (joined_handles if 'joined_handles' in dir() else set())]
    log.warning("Coordination join timeout — missing: %s", missing)
    return False


# ── Terminal state polling ────────────────────────────────────────────────────


def poll_for_terminal_state(
    api: MyceliumAPI,
    room: str,
    *,
    timeout: int = 600,
    poll_interval: int = 5,
    seen_message_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """Poll room messages until an l9_commit appears.

    Returns a result dict::

        {
            "converged": bool,
            "subkind": "converged" | "rejected",
            "commit": {...},   # full l9_commit payload
        }

    Returns ``None`` on timeout.
    """
    if seen_message_ids is None:
        seen_message_ids = set()

    deadline = time.time() + timeout
    last_log = 0.0

    while time.time() < deadline:
        _, msgs = api.get_room_messages(room, limit=100)
        if isinstance(msgs, list):
            for m in msgs:
                mid = str(m.get("id") or m.get("message_id") or "")
                if mid and mid in seen_message_ids:
                    continue
                commit = _parse_l9_commit(m)
                if commit is not None:
                    subkind = commit.get("l9", {}).get("header", {}).get("subkind", "")
                    return {
                        "converged": subkind == SUBKIND_CONVERGED,
                        "subkind": subkind,
                        "commit": commit,
                    }
                if mid:
                    seen_message_ids.add(mid)

        now = time.time()
        if now - last_log >= 30:
            log.info(
                "poll_for_terminal_state: waiting on %s (%.0fs remaining)",
                room, deadline - now,
            )
            last_log = now
        time.sleep(poll_interval)

    log.warning("poll_for_terminal_state timed out after %ds for %s", timeout, room)
    return None


# ── Response tracking ─────────────────────────────────────────────────────────


@dataclass
class RoundSnapshot:
    """Per-handle response counts observed in the room."""

    responses: dict[str, int] = field(default_factory=dict)

    @property
    def all_responded(self) -> bool:
        return bool(self.responses) and all(v > 0 for v in self.responses.values())

    def total_responses(self) -> int:
        return sum(self.responses.values())


def collect_room_responses(
    api: MyceliumAPI,
    room: str,
    expected_handles: list[str],
) -> RoundSnapshot:
    """Count ``broadcast`` messages per expected handle in *room*."""
    _, msgs = api.get_room_messages(room, limit=200)
    counts = {h: 0 for h in expected_handles}
    if isinstance(msgs, list):
        for m in msgs:
            if m.get("message_type") == "broadcast":
                handle = m.get("sender_handle") or ""
                if handle in counts:
                    counts[handle] += 1
    return RoundSnapshot(responses=counts)


# ── Setup helpers ─────────────────────────────────────────────────────────────


@dataclass
class CoordinationSetup:
    """Result of :func:`setup_coordination`."""

    room: str
    aligner_handle: str
    agent_handles: list[str]


def setup_coordination(
    api: MyceliumAPI,
    cli: MyceliumCLI,
    room: str,
    agent_handles: list[str],
    opening_positions: dict[str, str] | None = None,
    aligner_handle: str = "aligner",
) -> CoordinationSetup | None:
    """Create agents, post opening positions, and create the aligner engine.

    Does NOT invoke the aligner — invoke it AFTER starting await loops so
    agents are present in the roster when the aligner checks.

    Args:
        opening_positions: map of handle → opening position text.
            Defaults to a generic stub position for each agent.
    """
    default_position = "I hold a position on this topic that requires discussion."

    # Create agents (ignore "already exists" errors)
    for handle in agent_handles:
        r = cli.agent_create(handle, room, adapter="claude_code")
        if not r.ok and "already" not in r.error_message.lower():
            log.warning("agent create for %s: %s", handle, r.error_message)

    # Post opening positions
    positions = opening_positions or {}
    for handle in agent_handles:
        pos = positions.get(handle, default_position)
        r = cli.respond(room, handle, pos)
        if not r.ok:
            log.warning("respond (opening position) for %s: %s", handle, r.error_message)

    # Create aligner engine (idempotent)
    r = cli.engine_create(aligner_handle, room, kind="aligner")
    if not r.ok and "already" not in r.error_message.lower():
        log.warning("engine create: %s", r.error_message)

    return CoordinationSetup(
        room=room,
        aligner_handle=aligner_handle,
        agent_handles=agent_handles,
    )


# ── Debug helpers ─────────────────────────────────────────────────────────────


def collect_debug_info(
    api: MyceliumAPI,
    room: str,
    expected_handles: list[str],
) -> dict[str, Any]:
    """Gather room messages and response counts for failure diagnostics."""
    debug: dict[str, Any] = {
        "room": room,
        "expected_handles": expected_handles,
    }
    _, msgs = api.get_room_messages(room, limit=100)
    if isinstance(msgs, list):
        debug["recent_messages"] = [
            {
                "type": m.get("message_type"),
                "sender": m.get("sender_handle"),
                "preview": (m.get("content") or "")[:120],
            }
            for m in msgs[-20:]
        ]
        snap = collect_room_responses(api, room, expected_handles)
        debug["response_counts"] = snap.responses
    return debug
