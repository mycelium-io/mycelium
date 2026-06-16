"""Shared IOC coordination helpers for pyATS testcases.

SKILL-faithful negotiation flow (OpenClaw / Hermes / daemon cold-spawn):

1. Harness creates the session and ``session join`` for each agent.
2. Gateway or ``mycelium-daemon`` delivers ticks; agents respond via
   ``mycelium negotiate`` on their own — the harness never impersonates
   agents with ``negotiate respond`` or ``session await``.
3. Harness polls the backend for agent ``direct`` replies and terminal
   ``coordination_state`` / ``coordination_consensus``.

Mirrors ``mycelium_e2e/distributed_e2e.wait_for_negotiation_responses`` and
``libs/sessions.poll_consensus`` used by the matrix scenario tests.
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


@dataclass
class AgentResponseSnapshot:
    """Per-handle ``direct`` messages observed in the session room."""

    responses: dict[str, list[str]] = field(default_factory=dict)

    @property
    def all_responded(self) -> bool:
        return bool(self.responses) and all(self.responses.values())


def parse_session_room_from_cli(stdout: str, parent_room: str) -> str | None:
    """Extract session room name from ``mycelium --json session create`` output."""
    if not stdout.strip():
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    for key in ("session_room", "display_name", "room"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val

    nested = data.get("session")
    if isinstance(nested, dict):
        for key in ("session_room", "display_name", "room"):
            val = nested.get(key)
            if isinstance(val, str) and val:
                return val

    return None


def resolve_session_room(
    api: MyceliumAPI,
    parent_room: str,
    cli_stdout: str = "",
    poll_seconds: float = 10.0,
) -> str | None:
    """Resolve the child session room under *parent_room*."""
    session_room = parse_session_room_from_cli(cli_stdout, parent_room)
    if session_room:
        return session_room

    deadline = time.time() + poll_seconds
    while time.time() < deadline:
        session_room = api.find_session_room(parent_room)
        if session_room:
            return session_room
        time.sleep(0.5)
    return None


def wait_for_message_type(
    api: MyceliumAPI,
    room: str,
    message_type: str,
    timeout: int = 240,
    poll_interval: int = 5,
) -> bool:
    """Poll room messages until *message_type* appears or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, msgs = api.get_room_messages(room, limit=50)
        if any(m.get("message_type") == message_type for m in msgs):
            return True
        time.sleep(poll_interval)
    return False


def wait_for_coordination_tick(
    api: MyceliumAPI,
    room: str,
    timeout: int = 240,
    poll_interval: int = 5,
) -> bool:
    return wait_for_message_type(api, room, "coordination_tick", timeout, poll_interval)


def wait_for_coordination_consensus(
    api: MyceliumAPI,
    room: str,
    timeout: int = 240,
    poll_interval: int = 5,
) -> dict[str, Any] | None:
    """Poll messages for coordination_consensus; return parsed payload or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, msgs = api.get_room_messages(room, limit=50)
        for m in msgs:
            if m.get("message_type") != "coordination_consensus":
                continue
            content = m.get("content") or "{}"
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"raw": content}
        time.sleep(poll_interval)
    return None


def collect_agent_responses(
    messages: list[dict[str, Any]],
    expected_handles: list[str],
    *,
    seen_ids: set[str] | None = None,
) -> AgentResponseSnapshot:
    """Scan *messages* for ``direct`` replies from *expected_handles*."""
    responses: dict[str, list[str]] = {handle: [] for handle in expected_handles}
    for msg in messages:
        mid = msg.get("id")
        if mid is not None:
            if seen_ids is not None:
                if mid in seen_ids:
                    continue
                seen_ids.add(str(mid))
        if msg.get("message_type") != "direct":
            continue
        handle = msg.get("sender_handle")
        if handle in responses:
            responses[handle].append(msg.get("content") or "")
    return AgentResponseSnapshot(responses=responses)


def wait_for_agent_responses(
    api: MyceliumAPI,
    session_room: str,
    expected_handles: list[str],
    *,
    timeout: int = 240,
    poll_interval: int = 5,
) -> AgentResponseSnapshot:
    """Poll until every expected handle posts ≥1 ``direct`` message.

    Authoritative check that gateway/daemon agents participated — they
    reply via ``mycelium negotiate respond/propose``, not via harness CLI.
    """
    if not session_room:
        log.warning("wait_for_agent_responses: no session_room provided")
        return AgentResponseSnapshot(responses={h: [] for h in expected_handles})

    deadline = time.time() + timeout
    seen_ids: set[str] = set()
    snapshot = AgentResponseSnapshot(responses={h: [] for h in expected_handles})

    while time.time() < deadline:
        _, msgs = api.get_room_messages(session_room, limit=200)
        snapshot = collect_agent_responses(msgs, expected_handles, seen_ids=seen_ids)
        if snapshot.all_responded:
            log.info(
                "All %d agents replied in %s",
                len(expected_handles),
                session_room,
            )
            return snapshot
        time.sleep(poll_interval)

    log.warning(
        "Timeout waiting for agent responses in %s: %s",
        session_room,
        [(h, len(v)) for h, v in snapshot.responses.items()],
    )
    return snapshot


def collect_negotiation_debug(
    api: MyceliumAPI,
    cli: MyceliumCLI,
    parent_room: str,
    session_room: str,
    expected_handles: list[str],
) -> dict[str, Any]:
    """Gather room state, recent messages, and negotiate status for failures."""
    debug: dict[str, Any] = {
        "parent_room": parent_room,
        "session_room": session_room,
        "expected_handles": expected_handles,
    }

    for label, room in (("parent", parent_room), ("session", session_room)):
        status, data = api.get_room(room)
        debug[f"{label}_room_status"] = status
        if status == 200 and isinstance(data, dict):
            debug[f"{label}_coordination_state"] = data.get("coordination_state")

    _, msgs = api.get_room_messages(session_room, limit=100)
    debug["message_types"] = [
        {
            "type": m.get("message_type"),
            "sender": m.get("sender_handle"),
            "preview": (m.get("content") or "")[:120],
        }
        for m in msgs[-20:]
    ]
    debug["agent_responses"] = collect_agent_responses(
        msgs,
        expected_handles,
    ).responses

    status_r = cli.negotiate_status(session_room)
    debug["negotiate_status_ok"] = status_r.ok
    if status_r.ok and status_r.json is not None:
        debug["negotiate_status"] = status_r.json
    else:
        debug["negotiate_status_error"] = status_r.error_message

    return debug


def run_agent_driven_negotiation(
    api: MyceliumAPI,
    cli: MyceliumCLI,
    parent_room: str,
    agents: list[tuple[str, str]],
    *,
    negotiation_timeout: int = 600,
    poll_interval: int = 5,
) -> dict[str, Any] | None:
    """Create session, join agents, wait for autonomous agent negotiation.

    *agents* is a list of ``(handle, position_message)`` tuples. The harness
    only performs setup (``session create`` + ``session join``); real agents
    must respond to CFN ticks via their adapter (OpenClaw gateway,
    ``mycelium-daemon`` cold-spawn, Hermes gateway, etc.).

    Returns the session-room dict when ``coordination_state == complete``,
    the session-room dict for terminal ``failed``/``aborted``, or ``None``
    on timeout (with a debug dump logged).
    """
    expected_handles = [handle for handle, _ in agents]

    r = cli.session_create(parent_room)
    if not r.ok:
        log.error("session create failed: %s", r.error_message)
        return None

    session_room = resolve_session_room(api, parent_room, r.stdout)
    if not session_room:
        log.error("could not resolve session room for %s", parent_room)
        return None

    for handle, position in agents:
        jr = cli.session_join(parent_room, handle, position=position)
        if not jr.ok:
            log.error("session join failed for %s: %s", handle, jr.error_message)
            return None

    if not wait_for_message_type(
        api,
        session_room,
        "coordination_start",
        timeout=120,
        poll_interval=2,
    ):
        log.warning(
            "coordination_start not seen within 120s for %s — continuing",
            session_room,
        )

    deadline = time.time() + negotiation_timeout
    seen_ids: set[str] = set()
    last_progress = 0.0
    saw_tick = False
    agent_snapshot = AgentResponseSnapshot(responses={h: [] for h in expected_handles})

    while time.time() < deadline:
        status, data = api.get_room(session_room)
        if status == 200 and isinstance(data, dict):
            state = data.get("coordination_state")
            if state == "complete":
                log.info("negotiation complete for %s", session_room)
                return data
            if state in ("failed", "aborted"):
                debug = collect_negotiation_debug(
                    api,
                    cli,
                    parent_room,
                    session_room,
                    expected_handles,
                )
                log.error(
                    "coordination ended with state=%s for %s debug=%s",
                    state,
                    session_room,
                    json.dumps(debug, default=str)[:4000],
                )
                return data

        _, msgs = api.get_room_messages(session_room, limit=200)
        if not saw_tick and any(m.get("message_type") == "coordination_tick" for m in msgs):
            saw_tick = True
            log.info("coordination_tick observed in %s", session_room)

        agent_snapshot = collect_agent_responses(
            msgs,
            expected_handles,
            seen_ids=seen_ids,
        )

        for m in msgs:
            if m.get("message_type") == "coordination_consensus":
                log.debug("coordination_consensus seen for %s", session_room)
                break

        now = time.time()
        if now - last_progress >= 30:
            log.info(
                "negotiation progress %s: tick=%s responses=%s remaining=%.0fs",
                session_room,
                saw_tick,
                [(h, len(v)) for h, v in agent_snapshot.responses.items()],
                deadline - now,
            )
            last_progress = now

        time.sleep(poll_interval)

    debug = collect_negotiation_debug(
        api,
        cli,
        parent_room,
        session_room,
        expected_handles,
    )
    log.error(
        "negotiation did not reach complete within %ds for %s debug=%s",
        negotiation_timeout,
        session_room,
        json.dumps(debug, default=str)[:4000],
    )
    return None
