"""Cursor provisioner: creates per-test cursor agents via the mycelium CLI.

The cursor adapter spins up a fresh agent per scenario (each gets its own
temp workspace + identity); no global "claire-agent" equivalent exists.
That means :meth:`CursorProvisioner.create_agent` actually does work
(unlike the openclaw provisioner which just verifies a pre-existing
agent):

1. Make a workspace dir on the device (``mktemp -d /tmp/cursor-e2e-XXX``).
2. Run ``mycelium agent create <handle> --adapter cursor --cwd <workspace>
   --room <room>``.
3. Subscribe the cc-daemon to the room so it sees coordination ticks.

``wake_agent`` calls ``mycelium agent invoke`` which kicks the daemon
into dispatching the agent's first turn. The daemon then auto-attends
subsequent ticks via its room subscription, so the explicit wake is
only needed once per session.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Any, ClassVar

from libs import host_exec
from libs.host_exec import HostExecError
from libs.provisioners.base import ABCProvisioner, AgentRef, PrereqMissing

log = logging.getLogger(__name__)


class CursorProvisioner(ABCProvisioner):
    """Provisioner for the cursor adapter.

    Cursor doesn't carry cross-scenario runtime state — every test
    gets a fresh workspace — so the two-phase lifecycle collapses to:
    ``ensure_runtime`` is a no-op (inherited from
    :class:`ABCProvisioner`), and ``register_in_room`` /
    ``unregister_from_room`` forward to the legacy
    ``create_agent`` / ``cleanup_agent`` methods. The defaults in
    :class:`ABCProvisioner` make this wiring automatic.
    """

    name: ClassVar[str] = "cursor"

    # ── prereqs ────────────────────────────────────────────────────────

    def check_prereqs(self, device: Any) -> None:
        """Ensure cursor-agent and mycelium-cc-daemon are reachable."""
        try:
            mycelium = host_exec.execute(device, ["mycelium", "--version"], timeout=15.0)
        except HostExecError as exc:
            raise PrereqMissing(f"cursor: dispatch failed: {exc}") from exc
        if mycelium.returncode != 0:
            raise PrereqMissing(
                f"cursor: `mycelium --version` exited {mycelium.returncode}: {mycelium.stderr.strip()[:200]}"
            )

        # cursor-agent must be on PATH (added by host_exec's shell prelude)
        try:
            ca = host_exec.execute(device, ["which", "cursor-agent"], timeout=10.0)
        except HostExecError as exc:
            raise PrereqMissing(f"cursor: dispatch failed: {exc}") from exc
        if ca.returncode != 0 or "cursor-agent" not in ca.stdout:
            raise PrereqMissing(f"cursor: cursor-agent binary not found on {host_exec.describe(device)}")

        # cc-daemon must be running for room subscription + invoke
        try:
            daemon = host_exec.execute(device, ["mycelium", "daemon", "status"], timeout=10.0)
        except HostExecError as exc:
            raise PrereqMissing(f"cursor: dispatch failed: {exc}") from exc
        if daemon.returncode != 0:
            raise PrereqMissing(
                f"cursor: mycelium-cc-daemon not responsive on "
                f"{host_exec.describe(device)}: {daemon.stderr.strip()[:200]}"
            )

        try:
            auth = host_exec.execute(device, ["cursor-agent", "status"], timeout=15.0)
        except HostExecError as exc:
            raise PrereqMissing(f"cursor: dispatch failed: {exc}") from exc
        if not _cursor_agent_authenticated(auth):
            raise PrereqMissing(
                f"cursor: cursor-agent not authenticated on {host_exec.describe(device)} — "
                "run `cursor-agent login` on that host before e2e tests"
            )

    # ── create ────────────────────────────────────────────────────────

    def create_agent(
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,  # noqa: ARG002 - opening used during wake_agent
    ) -> AgentRef:
        """Create a fresh cursor agent with a per-test workspace."""
        workspace = self._make_workspace(device)
        log.info(
            "cursor.create_agent: %s on %s in %s",
            handle,
            host_exec.describe(device),
            workspace,
        )

        # Subscribe the daemon to the room BEFORE creating the agent so
        # the agent's first tick isn't missed. In compose containers use
        # the infra script — older CLI builds fall back to systemctl.
        sub = host_exec.execute(
            device,
            ["/openclaw/daemon-subscribe.sh", room],
            timeout=15.0,
        )
        if sub.returncode != 0:
            sub = host_exec.execute(
                device,
                ["mycelium", "daemon", "subscribe", room],
                timeout=15.0,
            )
        if sub.returncode != 0:
            raise PrereqMissing(f"cursor: daemon subscribe to {room} failed: {sub.stderr.strip()[:200]}")

        result = host_exec.execute(
            device,
            [
                "mycelium",
                "agent",
                "create",
                handle,
                "--adapter",
                "cursor",
                "--cwd",
                workspace,
                "--room",
                room,
            ],
            timeout=30.0,
        )
        if result.returncode != 0:
            raise PrereqMissing(f"cursor: `mycelium agent create {handle}` failed: {result.stderr.strip()[:200]}")

        ref = AgentRef(
            handle=handle,
            adapter=self.name,
            device_name=getattr(device, "name", None) or str(device),
            metadata={"workspace": workspace, "room": room},
        )

        return ref

    # ── wake ──────────────────────────────────────────────────────────

    def wake_agent(
        self,
        device: Any,
        agent: AgentRef,
        session_room: str,
    ) -> None:
        """Invoke the agent to kick off its first negotiation turn.

        The daemon is already subscribed to the room from
        :meth:`create_agent`, so subsequent ticks come in automatically.
        This wake is the cursor-equivalent of openclaw's Matrix DM.
        """
        message = f"Please join the negotiation in room {session_room} and post your opening position."
        try:
            result = host_exec.execute(
                device,
                [
                    "mycelium",
                    "agent",
                    "invoke",
                    agent.handle,
                    message,
                    "--room",
                    session_room,
                ],
                timeout=90.0,
            )
        except HostExecError as exc:
            log.warning(
                "cursor.wake_agent: dispatch failed for %s: %s",
                agent.handle,
                exc,
            )
            return
        if result.returncode != 0:
            log.warning(
                "cursor.wake_agent: invoke %s failed: %s",
                agent.handle,
                result.stderr.strip()[:300],
            )

    # ── cleanup ───────────────────────────────────────────────────────

    def cleanup_agent(
        self,
        device: Any,
        agent: AgentRef,
        room: str,
    ) -> None:
        """Remove agent, unsubscribe daemon, and delete workspace.

        Each step is best-effort: a failure earlier in the chain
        shouldn't prevent the others from running.
        """
        # 1. mycelium agent rm
        try:
            r = host_exec.execute(
                device,
                ["mycelium", "agent", "rm", agent.handle, "--force", "--room", room],
                timeout=15.0,
            )
            if r.returncode != 0:
                log.warning(
                    "cursor.cleanup_agent: agent rm %s failed: %s",
                    agent.handle,
                    r.stderr.strip()[:200],
                )
        except HostExecError as exc:
            log.warning("cursor.cleanup_agent: agent rm dispatch failed: %s", exc)

        # 2. daemon unsubscribe
        try:
            host_exec.execute(
                device,
                ["mycelium", "daemon", "unsubscribe", room],
                timeout=15.0,
            )
        except HostExecError as exc:
            log.debug("cursor.cleanup_agent: daemon unsubscribe failed: %s", exc)

        # 3. delete workspace (only if it matches the safe prefix)
        workspace = agent.metadata.get("workspace") or ""
        if not workspace.startswith("/tmp/cursor-e2e-"):
            log.warning(
                "cursor.cleanup_agent: refusing to remove %r (not a cursor-e2e workspace)",
                workspace,
            )
            return
        try:
            host_exec.execute(device, ["rm", "-rf", workspace], timeout=15.0)
        except HostExecError as exc:
            log.debug("cursor.cleanup_agent: workspace rm failed: %s", exc)

    # ── helpers ───────────────────────────────────────────────────────

    def _make_workspace(self, device: Any) -> str:
        """Create a temp workspace dir, seed it, and return its absolute path.

        ``mktemp -d /tmp/cursor-e2e-XXXXXX`` is used so cleanup can
        verify the prefix before issuing ``rm -rf``.

        The workspace is seeded with a minimal ``.cursor/rules/mycelium.mdc``
        so cursor-agent indexes the workspace immediately rather than
        discovering it cold on the first negotiation tick (#4 — workspace
        pre-indexing).
        """
        try:
            result = host_exec.execute(
                device,
                ["mktemp", "-d", "/tmp/cursor-e2e-XXXXXX"],
                timeout=10.0,
            )
        except HostExecError as exc:
            raise PrereqMissing(f"cursor: mktemp dispatch failed: {exc}") from exc
        path = result.stdout.strip()
        # Defence in depth: confirm it really is a /tmp/cursor-e2e- path
        if not _SAFE_WORKSPACE_RE.match(path):
            raise PrereqMissing(f"cursor: mktemp produced unexpected path {path!r}")

        # Seed the workspace so cursor-agent has something to index on
        # first load — avoids the cold-discovery penalty on the first tick.
        seed_cmds = [
            f"mkdir -p {path}/.cursor/rules",
            (
                f"printf 'You are a mycelium negotiation agent.\\n"
                f"Follow the mycelium SKILL.md protocol for session respond.\\n' "
                f"> {path}/.cursor/rules/mycelium.mdc"
            ),
        ]
        for cmd in seed_cmds:
            try:
                host_exec.execute(device, cmd, shell=True, timeout=5.0)
            except HostExecError as exc:
                log.warning("cursor: workspace seed step failed (continuing): %s", exc)

        return path

    def _pre_warm(self, device: Any, handle: str, room: str) -> None:
        """Fire a no-op invoke so cursor-agent loads the model before the first tick.

        The daemon spawns a cursor-agent process on the first invoke. By
        triggering that spawn against the bootstrap room (not the session
        room) immediately after agent creation, the model and workspace
        index are warm by the time the first negotiation tick arrives —
        cutting cold-start latency off round 0 (#1 — pre-warm).
        """
        log.info("cursor._pre_warm: warming %s via no-op invoke on %s", handle, room)
        try:
            host_exec.execute(
                device,
                [
                    "mycelium",
                    "agent",
                    "invoke",
                    handle,
                    "You are warming up. Reply with one word: ready.",
                    "--room",
                    room,
                ],
                timeout=120.0,
            )
        except HostExecError as exc:
            log.warning("cursor._pre_warm: invoke failed (non-fatal): %s", exc)


_SAFE_WORKSPACE_RE = re.compile(r"^/tmp/cursor-e2e-[A-Za-z0-9]{6,}$")

_AUTH_SUCCESS_MARKERS = (
    "login successful",
    "logged in with",
    "authenticated",
)
_AUTH_FAILURE_MARKERS = (
    "authentication required",
    "not authenticated",
    "not logged in",
    "please log in",
    "please run `cursor-agent login`",
)


def _cursor_agent_authenticated(result: subprocess.CompletedProcess[str]) -> bool:
    """Return True when ``cursor-agent status`` indicates a usable session."""
    combined = (result.stdout + result.stderr).lower()
    if any(marker in combined for marker in _AUTH_SUCCESS_MARKERS):
        return True
    if result.returncode != 0 and any(marker in combined for marker in _AUTH_FAILURE_MARKERS):
        return False
    # Unknown output with non-zero exit — treat as unauthenticated.
    return result.returncode == 0
