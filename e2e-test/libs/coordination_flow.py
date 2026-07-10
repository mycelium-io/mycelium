"""Shared IOC coordination helpers for pyATS testcases.

SKILL-faithful negotiation flow (OpenClaw / Hermes / daemon cold-spawn):

1. Harness creates the session and ``session join`` for each agent.
2. Gateway or ``mycelium-daemon`` delivers ticks; agents respond via
   ``mycelium negotiate`` on their own — the harness never impersonates
   agents with ``negotiate respond`` or ``session await``.
3. Harness polls the backend for agent ``direct`` replies and terminal
   negotiation outcomes via ``poll_for_consensus`` / ``poll_room_consensus_outcome``.
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

TERMINAL_COMPLETE_STATES = frozenset({"complete", "agreed"})
TERMINAL_FAILED_STATES = frozenset({"failed", "aborted"})


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


def find_coordination_consensus(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return parsed ``coordination_consensus`` payload from *messages*, if any."""
    for m in messages:
        if m.get("message_type") != "coordination_consensus":
            continue
        content = m.get("content") or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"raw": content}
    return None


def get_coordination_session(
    api: MyceliumAPI,
    parent_room: str,
    session_room: str,
) -> dict[str, Any] | None:
    """Look up the ``CoordinationSession`` row for *session_room* under *parent_room*."""
    status, data = api.get_coordination_sessions(parent_room=parent_room, limit=50)
    if status != 200 or not isinstance(data, list):
        return None
    for session in data:
        if session.get("display_name") == session_room:
            return session
    return None


def _negotiation_result(
    session_room: str,
    *,
    source: str,
    coordination_state: str = "complete",
    consensus: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "session_room": session_room,
        "coordination_state": coordination_state,
        "completion_source": source,
    }
    if consensus is not None:
        result["consensus"] = consensus
    if session is not None:
        result["session"] = session
    return result


def poll_room_consensus_outcome(
    api: MyceliumAPI,
    parent_room: str,
    *,
    session_room: str | None = None,
) -> dict[str, Any] | None:
    """Detect a terminal negotiation outcome for *parent_room*.

    When ``session_room`` is set, only that coordination session is
    considered.  This avoids picking up a prior testcase's terminal
    session when several sessions share one suite parent room.

    Parent rooms no longer expose ``coordination_state``; completion is
    observed via ``coordination_sessions.state`` or a ``coordination_consensus``
    message (posted on the parent listing, which includes session sub-room
    traffic).
    """
    if session_room:
        return poll_negotiation_completion(api, None, parent_room, session_room)

    status, data = api.get_coordination_sessions(parent_room=parent_room, limit=20)
    if status == 200 and isinstance(data, list):
        for session in sorted(
            data,
            key=lambda s: s.get("created_at") or "",
            reverse=True,
        ):
            state = session.get("state")
            session_room = session.get("display_name") or parent_room
            if state in TERMINAL_COMPLETE_STATES:
                result = _negotiation_result(
                    session_room,
                    source="coordination_session",
                    session=session,
                )
                return _attach_consensus_payload(
                    api,
                    result,
                    session_room=session_room,
                    parent_room=parent_room,
                )
            if state in TERMINAL_FAILED_STATES:
                result = _negotiation_result(
                    session_room,
                    source="coordination_session",
                    coordination_state=str(state),
                    session=session,
                )
                return _attach_consensus_payload(
                    api,
                    result,
                    session_room=session_room,
                    parent_room=parent_room,
                )

    _, msgs = api.get_room_messages(parent_room, limit=200)
    consensus = find_coordination_consensus(msgs)
    if consensus is not None:
        session_room = consensus.get("session") or parent_room
        if consensus.get("broken"):
            return _negotiation_result(
                session_room,
                source="coordination_consensus",
                coordination_state="failed",
                consensus=consensus,
            )
        return _negotiation_result(
            session_room,
            source="coordination_consensus",
            consensus=consensus,
        )

    return None


def poll_for_consensus(
    api: MyceliumAPI,
    parent_room: str,
    *,
    session_room: str | None = None,
    timeout: int = 600,
    poll_interval: int = 5,
) -> dict[str, Any] | None:
    """Poll until *parent_room* (or *session_room*) reaches a terminal outcome."""
    deadline = time.time() + timeout
    last_log = 0.0
    target = session_room or parent_room
    while time.time() < deadline:
        outcome = poll_room_consensus_outcome(
            api,
            parent_room,
            session_room=session_room,
        )
        if outcome is not None:
            state = outcome.get("coordination_state")
            if state in TERMINAL_FAILED_STATES:
                log.warning(
                    "Coordination ended with state=%s for %s",
                    state,
                    target,
                )
            return outcome

        now = time.time()
        if now - last_log >= 30:
            log.info(
                "poll_for_consensus: still waiting on %s (%.0fs remaining)",
                target,
                deadline - now,
            )
            last_log = now
        time.sleep(poll_interval)

    log.warning("poll_for_consensus timed out after %ds for %s", timeout, target)
    return None


@dataclass
class AgentNegotiationSetup:
    """Session plumbing created by :func:`setup_agent_driven_negotiation`."""

    session_room: str
    expected_handles: list[str]


def setup_agent_driven_negotiation(
    api: MyceliumAPI,
    cli: MyceliumCLI,
    parent_room: str,
    agents: list[tuple[str, str]],
) -> AgentNegotiationSetup | None:
    """Create a coordination session and join *agents* with opening positions.

    Real agents must respond to CFN ticks via their adapter after this returns.
    Returns ``None`` when session create/join fails.
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

    return AgentNegotiationSetup(
        session_room=session_room,
        expected_handles=expected_handles,
    )


def log_negotiation_poll_failure(
    api: MyceliumAPI,
    cli: MyceliumCLI,
    parent_room: str,
    setup: AgentNegotiationSetup,
    result: dict[str, Any] | None,
    *,
    timeout: int,
) -> None:
    """Emit a debug bundle when :func:`poll_for_consensus` times out or fails."""
    state = result.get("coordination_state") if isinstance(result, dict) else None
    debug = collect_negotiation_debug(
        api,
        cli,
        parent_room,
        setup.session_room,
        setup.expected_handles,
    )
    log.error(
        "negotiation poll failed for %s state=%s timeout=%ds debug=%s",
        setup.session_room,
        state,
        timeout,
        json.dumps(debug, default=str)[:4000],
    )


def _attach_consensus_payload(
    api: MyceliumAPI,
    result: dict[str, Any],
    *,
    session_room: str,
    parent_room: str,
) -> dict[str, Any]:
    """Merge ``coordination_consensus`` message fields into *result* when present."""
    for room in (session_room, parent_room):
        if not room:
            continue
        _, msgs = api.get_room_messages(room, limit=200)
        consensus = find_coordination_consensus(msgs)
        if consensus is not None:
            result["consensus"] = consensus
            break
    return result


def poll_negotiation_completion(
    api: MyceliumAPI,
    cli: MyceliumCLI | None,
    parent_room: str,
    session_room: str,
) -> dict[str, Any] | None:
    """Return a terminal negotiation result dict, or ``None`` if still in progress.

    Session rooms are not ``rooms`` table rows (``GET /api/rooms/{session}`` → 404).
    Completion is detected via ``coordination_sessions.state``, a
    ``coordination_consensus`` message, or an inactive ``negotiate status`` after
    consensus was posted.
    """
    session = get_coordination_session(api, parent_room, session_room)
    if session is not None:
        state = session.get("state")
        if state in TERMINAL_COMPLETE_STATES:
            result = _negotiation_result(
                session_room,
                source="coordination_session",
                session=session,
            )
            return _attach_consensus_payload(
                api,
                result,
                session_room=session_room,
                parent_room=parent_room,
            )
        if state in TERMINAL_FAILED_STATES:
            result = _negotiation_result(
                session_room,
                source="coordination_session",
                coordination_state=str(state),
                session=session,
            )
            return _attach_consensus_payload(
                api,
                result,
                session_room=session_room,
                parent_room=parent_room,
            )

    _, msgs = api.get_room_messages(session_room, limit=200)
    consensus = find_coordination_consensus(msgs)
    if consensus is not None:
        if consensus.get("broken"):
            return _negotiation_result(
                session_room,
                source="coordination_consensus",
                coordination_state="failed",
                consensus=consensus,
            )
        return _negotiation_result(
            session_room,
            source="coordination_consensus",
            consensus=consensus,
        )

    return None


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
        consensus = find_coordination_consensus(msgs)
        if consensus is not None:
            return consensus
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
