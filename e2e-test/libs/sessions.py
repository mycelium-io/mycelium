"""Transport-agnostic session/negotiate/plan helpers.

The legacy ``libs/cursor.py`` and ``libs/openclaw.py`` modules shell out
locally or over SSH; this module instead routes every call through
:mod:`libs.host_exec` so the same scenario code runs in three places
without modification:

- locally against a dev workstation (``transport=local``)
- inside docker compose (``transport=docker``)
- against the real lab boxes via SSH (``transport=ssh``)

Everything here is *thin*: each function maps to one ``mycelium …`` CLI
call and surfaces stdout/stderr + a parsed JSON body where appropriate.
Polling logic lives next to the helpers so the scenarios module can stay
declarative.

Adapter awareness
-----------------

The CLI surface is adapter-agnostic — ``mycelium session create``,
``mycelium session join``, and ``mycelium negotiate respond`` all behave
the same regardless of whether the underlying agent is openclaw, cursor,
or hermes. The *delivery mechanism* differs (provisioner-specific wake
in openclaw + cursor; passive polling in hermes) — that part lives in
``libs.provisioners.*``, not here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from libs import host_exec
from libs.host_exec import HostExecError

log = logging.getLogger(__name__)


# ── data classes ─────────────────────────────────────────────────────


@dataclass
class ConsensusOutcome:
    """Terminal outcome of a negotiation session.

    ``broken=True`` indicates timeout / no-agreement — still a valid
    terminal state. ``broken=False`` means an actual agreement was
    reached. ``plan_file`` is set when the backend's plan compiler
    materialised ``plan/tasks.md`` (the standard happy path).
    """

    state: str  # "consensus" | "timeout" | "missing"
    broken: bool
    plan_file: str | None
    plan: str | None
    assignments: dict[str, Any]
    raw: dict[str, Any]

    @property
    def reached(self) -> bool:
        """True iff a real agreement (not a timeout) was reached."""
        return self.state == "consensus" and not self.broken


# ── room lifecycle ───────────────────────────────────────────────────


def create_room(device: Any, room: str, *, timeout: float = 15.0) -> None:
    """Create a room via ``mycelium room create``. Idempotent on the
    backend (a second create on the same name returns 200 with an
    "already exists" envelope) — we treat any non-zero exit code that
    contains ``already exists`` as success."""
    try:
        result = host_exec.execute(
            device,
            ["mycelium", "room", "create", room],
            timeout=timeout,
        )
    except HostExecError as exc:
        raise SessionError(f"create_room: dispatch failed: {exc}") from exc
    if result.returncode != 0 and "already exists" not in (result.stdout + result.stderr).lower():
        raise SessionError(
            f"create_room({room!r}) failed (rc={result.returncode}): {(result.stderr or result.stdout).strip()[:300]}"
        )


def delete_room(device: Any, room: str, *, timeout: float = 15.0) -> None:
    """Delete a room (best-effort; never raises)."""
    try:
        host_exec.execute(
            device,
            ["mycelium", "room", "delete", room, "--force"],
            timeout=timeout,
        )
    except HostExecError as exc:
        log.debug("delete_room: dispatch failed (ignored): %s", exc)


# ── session / negotiation ────────────────────────────────────────────


def session_create(
    device: Any,
    room: str,
    *,
    backend_url: str | None = None,
    timeout: float = 60.0,
) -> str:
    """Start a coordination session in the given room.

    Returns the child session room name (``parent:session:shortid``).
    """
    from libs.coordination_flow import parse_session_room_from_cli, resolve_session_room

    try:
        result = host_exec.execute(
            device,
            ["mycelium", "--json", "session", "create", "--room", room],
            timeout=timeout,
        )
    except HostExecError as exc:
        raise SessionError(f"session_create: dispatch failed: {exc}") from exc
    if result.returncode != 0:
        raise SessionError(
            f"session_create({room!r}) failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )

    session_room = parse_session_room_from_cli(result.stdout, room)
    if not session_room and backend_url:
        from libs.mycelium_api import MyceliumAPI

        api = MyceliumAPI(base_url=backend_url)
        session_room = resolve_session_room(api, room, result.stdout)

    if not session_room:
        raise SessionError(
            f"session_create({room!r}) succeeded but session room could not be resolved "
            f"from CLI output: {(result.stdout or result.stderr).strip()[:300]!r}"
        )
    return session_room


def session_join(
    device: Any,
    room: str,
    handle: str,
    position: str,
    *,
    timeout: float = 60.0,
) -> None:
    """Join the active coordination session in ``room`` with a one-sentence
    opening position. ``position`` must be non-empty — CognitiveEngine
    uses it to seed the first round."""
    if not position.strip():
        raise SessionError("session_join: position must be non-empty")
    try:
        result = host_exec.execute(
            device,
            [
                "mycelium",
                "session",
                "join",
                "--room",
                room,
                "--handle",
                handle,
                "--message",
                position,
            ],
            timeout=timeout,
        )
    except HostExecError as exc:
        raise SessionError(f"session_join: dispatch failed: {exc}") from exc
    if result.returncode != 0:
        raise SessionError(
            f"session_join({handle!r} in {room!r}) failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )


# ── memory ───────────────────────────────────────────────────────────


def memory_set(
    device: Any,
    room: str,
    handle: str,
    key: str,
    value: str,
    *,
    timeout: float = 30.0,
) -> None:
    """Write a memory; raises ``SessionError`` on non-zero exit."""
    try:
        result = host_exec.execute(
            device,
            [
                "mycelium",
                "memory",
                "set",
                "--room",
                room,
                "--handle",
                handle,
                key,
                value,
            ],
            timeout=timeout,
        )
    except HostExecError as exc:
        raise SessionError(f"memory_set: dispatch failed: {exc}") from exc
    if result.returncode != 0:
        raise SessionError(
            f"memory_set({key!r}) failed (rc={result.returncode}): {(result.stderr or result.stdout).strip()[:300]}"
        )


def memory_search(
    device: Any,
    room: str,
    query: str,
    *,
    timeout: float = 30.0,
) -> str:
    """Run a semantic search and return the raw CLI stdout.

    Scenarios decide how to score hits — usually via substring match on
    the row's ``expected_hit`` field.
    """
    try:
        result = host_exec.execute(
            device,
            ["mycelium", "memory", "search", "--room", room, query],
            timeout=timeout,
        )
    except HostExecError as exc:
        raise SessionError(f"memory_search: dispatch failed: {exc}") from exc
    if result.returncode != 0:
        raise SessionError(
            f"memory_search({query!r}) failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )
    return result.stdout


# ── consensus poller (HTTP, not CLI) ────────────────────────────────
#
# ``mycelium session await`` would do this for us but it's per-handle
# (only the agent who joined can await its own ticks). Scenarios need a
# room-wide outcome poller, so we hit the backend directly.


def consensus_outcome_from_poll(result: dict[str, Any] | None) -> ConsensusOutcome:
    """Convert a :func:`coordination_flow.poll_for_consensus` result to ``ConsensusOutcome``."""
    if result is None:
        return ConsensusOutcome(
            state="timeout",
            broken=True,
            plan_file=None,
            plan=None,
            assignments={},
            raw={},
        )

    consensus = result.get("consensus") or {}
    coord_state = result.get("coordination_state", "complete")
    broken = bool(consensus.get("broken")) or coord_state in ("failed", "aborted")
    return ConsensusOutcome(
        state="consensus",
        broken=broken,
        plan_file=consensus.get("plan_file"),
        plan=consensus.get("plan"),
        assignments=consensus.get("assignments") or {},
        raw=consensus if consensus else result,
    )


def poll_consensus(
    backend_url: str,
    room: str,
    *,
    session_room: str | None = None,
    timeout_seconds: int = 600,
    poll_interval: int = 5,
) -> ConsensusOutcome:
    """Poll the backend until *room* reaches a terminal negotiation outcome.

    When ``session_room`` is provided, only that coordination session is
    polled — required for shared suite parent rooms.
    """
    from libs.coordination_flow import poll_for_consensus
    from libs.mycelium_api import MyceliumAPI

    api = MyceliumAPI(base_url=backend_url)
    result = poll_for_consensus(
        api,
        room,
        session_room=session_room,
        timeout=timeout_seconds,
        poll_interval=poll_interval,
    )
    return consensus_outcome_from_poll(result)


# ── plan/tasks ───────────────────────────────────────────────────────


def read_plan_tasks(
    device: Any,
    room: str,
    *,
    timeout: float = 15.0,
) -> str:
    """Read the room's shared plan via ``mycelium memory get plan/tasks``.

    Returns the raw markdown body. Raises ``SessionError`` when the key
    is missing - scenarios that require a plan file fail loudly so the
    plan-compiler regression is visible in CI output.
    """
    try:
        result = host_exec.execute(
            device,
            [
                "mycelium",
                "memory",
                "get",
                "--room",
                room,
                "plan/tasks",
            ],
            timeout=timeout,
        )
    except HostExecError as exc:
        raise SessionError(f"read_plan_tasks: dispatch failed: {exc}") from exc
    if result.returncode != 0:
        raise SessionError(
            f"read_plan_tasks({room!r}) failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )
    return result.stdout


# ── errors ───────────────────────────────────────────────────────────


class SessionError(RuntimeError):
    """Raised when a session/negotiate/plan CLI call fails."""


# Coordination sessions in these states block ``session create`` on the
# parent room (mirrors the hermes plugin session poller).
_ACTIVE_COORDINATION_STATES = frozenset({"waiting", "negotiating"})
_TERMINAL_COORDINATION_STATES = frozenset({"complete", "agreed", "failed", "aborted"})
_SUITE_SESSION_DRAIN_SECONDS = 120.0


def wait_for_session_terminal(
    backend_url: str,
    parent_room: str,
    session_room: str,
    *,
    timeout_seconds: float = _SUITE_SESSION_DRAIN_SECONDS,
    poll_interval: float = 2.0,
) -> None:
    """Block until ``session_room`` reaches a terminal coordination state."""
    import time

    from libs.coordination_flow import get_coordination_session

    from libs.mycelium_api import MyceliumAPI

    api = MyceliumAPI(base_url=backend_url)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        session = get_coordination_session(api, parent_room, session_room)
        if session is None:
            return
        state = session.get("state")
        if state in _TERMINAL_COORDINATION_STATES:
            return
        log.info(
            "wait_for_session_terminal: %r still %s — waiting",
            session_room,
            state,
        )
        time.sleep(poll_interval)
    raise SessionError(
        f"coordination session {session_room!r} still active after "
        f"{timeout_seconds:.0f}s (parent={parent_room!r})"
    )


def wait_for_no_active_sessions(
    backend_url: str,
    parent_room: str,
    *,
    timeout_seconds: float = _SUITE_SESSION_DRAIN_SECONDS,
    poll_interval: float = 2.0,
) -> None:
    """Block until no coordination session on ``parent_room`` is active.

    Raises :class:`SessionError` when sessions remain active after
    ``timeout_seconds``.
    """
    import time

    from libs.mycelium_api import MyceliumAPI

    api = MyceliumAPI(base_url=backend_url)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status, data = api.get_coordination_sessions(parent_room=parent_room, limit=50)
        if status != 200:
            log.debug(
                "wait_for_no_active_sessions: GET coordination-sessions → %s",
                status,
            )
            time.sleep(poll_interval)
            continue
        entries = data if isinstance(data, list) else []
        active = [
            e
            for e in entries
            if isinstance(e, dict)
            and e.get("state") in _ACTIVE_COORDINATION_STATES
            and e.get("parent_room_name") == parent_room
        ]
        if not active:
            return
        log.info(
            "wait_for_no_active_sessions: %d active session(s) on %r — waiting",
            len(active),
            parent_room,
        )
        time.sleep(poll_interval)
    raise SessionError(
        f"active coordination session(s) still present on {parent_room!r} "
        f"after {timeout_seconds:.0f}s — prior testcase may have aborted mid-flight"
    )
