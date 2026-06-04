"""Hermes provisioner: agent lifecycle via the mycelium CLI.

Unlike cursor (per-test workspace) and openclaw (pre-configured agents
on each device), hermes agents are created on demand through
``mycelium agent create --adapter hermes``. The installer in
``mycelium-cli/src/mycelium/integrations/hermes/install.py`` patches the
gateway config and waits for the plugin to reconnect, so by the time
:meth:`HermesProvisioner.create_agent` returns the agent is already
subscribed to its room.

``wake_agent`` is a no-op: the hermes plugin polls coordination sessions
and auto-attends, so no Matrix DM or invoke call is needed.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from libs import host_exec
from libs.host_exec import HostExecError
from libs.provisioners.base import AgentRef, PrereqMissing

log = logging.getLogger(__name__)


class HermesProvisioner:
    """Provisioner for the hermes adapter."""

    name: ClassVar[str] = "hermes"

    # ── prereqs ────────────────────────────────────────────────────────

    def check_prereqs(self, device: Any) -> None:
        """Ensure mycelium CLI is reachable and the hermes adapter is registered.

        The deeper "is the gateway actually running" check is folded
        into :meth:`create_agent` - if gateway is down the
        ``mycelium agent create`` call will fail with a useful error
        message that we forward as ``PrereqMissing``.
        """
        try:
            mycelium = host_exec.execute(device, ["mycelium", "--version"], timeout=15.0)
        except HostExecError as exc:
            raise PrereqMissing(f"hermes: dispatch failed: {exc}") from exc
        if mycelium.returncode != 0:
            raise PrereqMissing(
                f"hermes: `mycelium --version` exited {mycelium.returncode}: {mycelium.stderr.strip()[:200]}"
            )

        # ``mycelium adapter ls`` exits non-zero when the adapter isn't
        # registered. Some lab hosts also expose a per-adapter
        # health check via ``mycelium doctor`` - we keep it simple and
        # just look for the string "hermes" in the listing.
        try:
            adapters = host_exec.execute(
                device,
                ["mycelium", "adapter", "ls"],
                timeout=15.0,
            )
        except HostExecError as exc:
            raise PrereqMissing(f"hermes: dispatch failed: {exc}") from exc
        if adapters.returncode != 0:
            raise PrereqMissing(
                f"hermes: `mycelium adapter ls` exited {adapters.returncode}: {adapters.stderr.strip()[:200]}"
            )
        if "hermes" not in adapters.stdout.lower():
            raise PrereqMissing(
                f"hermes: adapter not registered on "
                f"{host_exec.describe(device)} - run "
                "`mycelium adapter add hermes` first"
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
        """Create a hermes agent and rely on the installer to restart the gateway.

        The mycelium hermes installer's wait-and-verify step (see
        ``mycelium-cli/src/mycelium/integrations/hermes/install.py``)
        polls the hermes agent log for the plugin's "subscribed to N
        room(s)" message after each gateway restart, so by the time
        this call returns the room is already wired up.
        """
        log.info(
            "hermes.create_agent: %s on %s for room %s",
            handle,
            host_exec.describe(device),
            room,
        )

        # Generous timeout: the gateway restart + wait-and-verify can
        # take ~20s on a cold spoke (uv-installed CLI + hermes process
        # supervisor restart).
        result = host_exec.execute(
            device,
            [
                "mycelium",
                "agent",
                "create",
                handle,
                "--adapter",
                "hermes",
                "--room",
                room,
            ],
            timeout=60.0,
        )
        if result.returncode != 0:
            raise PrereqMissing(
                f"hermes: `mycelium agent create {handle}` failed "
                f"(returncode={result.returncode}): "
                f"{result.stderr.strip()[:300] or result.stdout.strip()[:300]}"
            )

        return AgentRef(
            handle=handle,
            adapter=self.name,
            device_name=getattr(device, "name", None) or str(device),
            metadata={"room": room},
        )

    # ── wake ──────────────────────────────────────────────────────────

    def wake_agent(
        self,
        device: Any,  # noqa: ARG002 - intentionally unused
        agent: AgentRef,
        session_room: str,
    ) -> None:
        """No-op: the hermes plugin polls coordination sessions and joins
        automatically. We log the call for parity with the openclaw /
        cursor provisioners but do not emit any wire traffic."""
        log.debug(
            "hermes.wake_agent: %s in %s - no-op (plugin polls)",
            agent.handle,
            session_room,
        )

    # ── cleanup ───────────────────────────────────────────────────────

    def cleanup_agent(
        self,
        device: Any,
        agent: AgentRef,
        room: str,
    ) -> None:
        """Remove the agent; the installer restarts the gateway on its own."""
        try:
            result = host_exec.execute(
                device,
                [
                    "mycelium",
                    "agent",
                    "rm",
                    agent.handle,
                    "--force",
                    "--room",
                    room,
                ],
                timeout=60.0,
            )
        except HostExecError as exc:
            log.warning("hermes.cleanup_agent: dispatch failed: %s", exc)
            return
        if result.returncode != 0:
            log.warning(
                "hermes.cleanup_agent: agent rm %s failed: %s",
                agent.handle,
                result.stderr.strip()[:200],
            )
