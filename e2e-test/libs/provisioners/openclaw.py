"""OpenClaw provisioner: wraps :mod:`libs.openclaw` via :mod:`libs.host_exec`.

OpenClaw agents are typically pre-configured on each host (see the
existing ``DISTRIBUTED_AGENTS`` dict in
:mod:`testcases.distributed_tests`). Stage 1 of the three-axis matrix
refactor preserves that assumption: :meth:`OpenClawProvisioner.create_agent`
verifies the agent is reachable via ``mycelium agent ls`` rather than
auto-creating one. Auto-creation lands in stage 2 alongside the
unified spoke image.

The wake path posts a Matrix DM (via :class:`libs.matrix_client.MatrixClient`)
when the device is a *spoke* and Matrix credentials are configured;
hub-resident agents see the session via the openclaw mycelium-room
channel plugin and need no external trigger.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, ClassVar

from libs import host_exec
from libs.host_exec import HostExecError
from libs.provisioners.base import AgentRef, PrereqMissing

log = logging.getLogger(__name__)


class OpenClawProvisioner:
    """Provisioner for the openclaw adapter.

    Read carefully: the constructor takes no arguments. The provisioner
    is intentionally stateless; per-device configuration travels through
    the pyATS Device's ``custom`` block (and is read on each call via
    :mod:`libs.host_exec`).
    """

    name: ClassVar[str] = "openclaw"

    # ── prereqs ────────────────────────────────────────────────────────

    def check_prereqs(self, device: Any) -> None:
        """Verify the mycelium CLI is reachable on ``device``.

        Raises :class:`PrereqMissing` so scenarios can convert to a
        ``self.skipped(...)`` cleanly.
        """
        try:
            result = host_exec.execute(
                device,
                ["mycelium", "--version"],
                timeout=15.0,
            )
        except HostExecError as exc:
            raise PrereqMissing(f"openclaw: dispatch failed: {exc}") from exc
        if result.returncode != 0:
            raise PrereqMissing(
                f"openclaw: `mycelium --version` exited {result.returncode}: {result.stderr.strip()[:200]}"
            )

    # ── create ────────────────────────────────────────────────────────

    def create_agent(
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,  # noqa: ARG002 - reserved for stage 3
    ) -> AgentRef:
        """Verify ``handle`` exists on ``device`` and return its ref.

        Stage 1 does NOT create openclaw agents on demand; it expects
        them to be pre-configured. ``raise PrereqMissing`` if the
        handle is unknown so scenarios skip rather than fail.
        """
        # Always scope to the target room. ``mycelium agent ls`` with
        # no ``--room`` flag and no active room set exits 1 with a
        # "No room specified" message — which we mistakenly took as a
        # missing-agent signal until we noticed the scenario suite
        # never sets ``rooms.active`` on the test device.
        try:
            result = host_exec.execute(
                device,
                ["mycelium", "agent", "ls", "--room", room],
                timeout=15.0,
            )
        except HostExecError as exc:
            raise PrereqMissing(f"openclaw: dispatch failed: {exc}") from exc
        if result.returncode != 0:
            raise PrereqMissing(
                f"openclaw: `mycelium agent ls --room {room}` exited "
                f"{result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
            )
        if handle not in result.stdout:
            raise PrereqMissing(
                f"openclaw: agent {handle!r} not found on "
                f"{host_exec.describe(device)} in room {room!r} — "
                "stage 1 expects pre-configured agents"
            )

        return AgentRef(
            handle=handle,
            adapter=self.name,
            device_name=getattr(device, "name", None) or str(device),
            metadata={
                "matrix_token_env": _matrix_token_env_for(handle),
                "room": room,
            },
        )

    # ── wake ──────────────────────────────────────────────────────────

    def wake_agent(
        self,
        device: Any,
        agent: AgentRef,
        session_room: str,
    ) -> None:
        """Post a Matrix DM trigger when ``device`` is a spoke.

        On the hub the openclaw mycelium-room channel plugin sees the
        session sub-room directly and no Matrix prod is needed. On
        spokes we fall back to the existing Matrix-trigger path that
        :mod:`testcases.distributed_tests` uses.
        """
        custom = getattr(device, "custom", {})
        role = (custom.get("role") if hasattr(custom, "get") else None) or ""
        if role.lower() != "spoke":
            log.debug(
                "openclaw.wake_agent: %s is %r, no Matrix trigger needed",
                host_exec.describe(device),
                role or "hub",
            )
            return

        matrix_url = os.environ.get("MATRIX_URL")
        room_id = os.environ.get("E2E_MATRIX_ROOM_ID")
        token = os.environ.get(agent.metadata.get("matrix_token_env", ""))
        if not (matrix_url and room_id and token):
            log.info(
                "openclaw.wake_agent: skipping Matrix trigger (matrix_url=%s, room_id=%s, token=%s)",
                bool(matrix_url),
                bool(room_id),
                bool(token),
            )
            return

        body = (
            f"@{agent.handle} please join the negotiation in room "
            f"{session_room}. Use `mycelium session join --room {session_room}`."
        )
        try:
            asyncio.run(_send_matrix_dm(matrix_url, token, room_id, body))
        except Exception as exc:  # noqa: BLE001 - logged and continued
            log.warning(
                "openclaw.wake_agent: Matrix trigger to %s failed: %s",
                agent.handle,
                exc,
            )

    # ── cleanup ───────────────────────────────────────────────────────

    def cleanup_agent(
        self,
        device: Any,
        agent: AgentRef,
        room: str,  # noqa: ARG002 - room is part of the matrix row, scenarios delete it
    ) -> None:
        """Best-effort reset of the agent's negotiation-carrying sessions.

        Mirrors :func:`libs.openclaw.reset_agent_sessions` but speaks
        through :mod:`host_exec`. Failures are logged, not raised - the
        scenario's own cleanup step deletes the test room regardless.
        """
        try:
            sessions = self._list_negotiation_sessions(device, agent.handle)
        except HostExecError as exc:
            log.warning(
                "openclaw.cleanup_agent: list sessions failed for %s on %s: %s",
                agent.handle,
                host_exec.describe(device),
                exc,
            )
            return

        for session in sessions:
            key = session.get("key") or session.get("sessionKey")
            if not key:
                continue
            try:
                proc = host_exec.execute(
                    device,
                    [
                        "openclaw",
                        "gateway",
                        "call",
                        "sessions.reset",
                        "--params",
                        json.dumps({"key": key}),
                    ],
                    timeout=15.0,
                )
            except HostExecError as exc:
                log.warning(
                    "openclaw.cleanup_agent: reset dispatch failed (%s/%s): %s",
                    agent.handle,
                    key,
                    exc,
                )
                continue
            if proc.returncode != 0:
                log.warning(
                    "openclaw.cleanup_agent: reset failed (%s/%s): %s",
                    agent.handle,
                    key,
                    proc.stderr.strip()[:200],
                )

    # ── helpers ───────────────────────────────────────────────────────

    def _list_negotiation_sessions(
        self,
        device: Any,
        agent_handle: str,
    ) -> list[dict[str, Any]]:
        proc = host_exec.execute(
            device,
            [
                "openclaw",
                "sessions",
                "--agent",
                agent_handle,
                "--json",
                "--limit",
                "100",
            ],
            timeout=20.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []
        sessions = data if isinstance(data, list) else data.get("sessions", [])
        # Keep only sessions tied to mycelium-room / matrix channels
        # (matches the existing libs.openclaw filter).
        return [
            s
            for s in sessions
            if any(tag in (s.get("key") or s.get("sessionKey") or "") for tag in ("mycelium-room", "matrix:channel:"))
        ]


# ── module-level helpers ──────────────────────────────────────────────


def _matrix_token_env_for(handle: str) -> str:
    """Convention: agent ``alpha`` -> ``MATRIX_TOKEN_AGENT_ALPHA``."""
    suffix = handle.replace("-", "_").upper()
    return f"MATRIX_TOKEN_{suffix}"


async def _send_matrix_dm(
    homeserver: str,
    token: str,
    room_id: str,
    body: str,
) -> None:
    """Send a single Matrix message via :class:`libs.matrix_client.MatrixClient`."""
    from libs.matrix_client import MatrixClient

    client = MatrixClient(homeserver=homeserver, access_token=token)
    try:
        await client.send_message(room_id, body)
    finally:
        await client.close()
