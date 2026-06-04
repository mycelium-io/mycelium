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

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

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


def session_create(device: Any, room: str, *, timeout: float = 60.0) -> None:
    """Start a coordination session in the given room."""
    try:
        result = host_exec.execute(
            device,
            ["mycelium", "session", "create", "--room", room],
            timeout=timeout,
        )
    except HostExecError as exc:
        raise SessionError(f"session_create: dispatch failed: {exc}") from exc
    if result.returncode != 0:
        raise SessionError(
            f"session_create({room!r}) failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )


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


def poll_consensus(
    backend_url: str,
    room: str,
    *,
    timeout_seconds: int = 600,
    poll_interval: int = 5,
) -> ConsensusOutcome:
    """Poll the backend until ``coordination_consensus`` is posted in
    ``room`` or the timeout expires.

    The consensus message lives in the *session sub-room*
    (``<room>:session:<short_id>``) but the backend's room-messages
    endpoint exposes child sub-room messages on the parent room's
    listing, so a single GET against the parent works. If you want
    sub-room-only resolution, set ``room`` to the session id explicitly.
    """
    deadline = time.time() + timeout_seconds
    consensus_url = f"{backend_url.rstrip('/')}/rooms/{quote(room, safe='')}/messages?limit=100"

    last_log = 0.0
    while time.time() < deadline:
        try:
            req = urllib.request.Request(consensus_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - http(s) only
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.debug("poll_consensus: HTTP error: %s", exc)
        else:
            for msg in data.get("messages", []):
                if msg.get("message_type") == "coordination_consensus":
                    return _parse_consensus_message(msg)

        # Throttled progress log every 30s so CI output stays readable.
        now = time.time()
        if now - last_log >= 30:
            log.info(
                "poll_consensus: still waiting on %s (%.0fs remaining)",
                room,
                deadline - now,
            )
            last_log = now
        time.sleep(poll_interval)

    log.warning(
        "poll_consensus: timed out after %ds on room %s",
        timeout_seconds,
        room,
    )
    return ConsensusOutcome(
        state="timeout",
        broken=True,
        plan_file=None,
        plan=None,
        assignments={},
        raw={},
    )


def _parse_consensus_message(msg: dict[str, Any]) -> ConsensusOutcome:
    """Turn a backend ``coordination_consensus`` message into a typed outcome."""
    content = msg.get("content", "{}")
    if isinstance(content, str):
        try:
            body = json.loads(content)
        except json.JSONDecodeError:
            body = {"plan": content}
    else:
        body = content or {}

    return ConsensusOutcome(
        state="consensus",
        broken=bool(body.get("broken")),
        plan_file=body.get("plan_file"),
        plan=body.get("plan"),
        assignments=body.get("assignments") or {},
        raw=body,
    )


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
