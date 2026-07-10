"""Hermes provisioner: agent lifecycle via the mycelium CLI.

Unlike cursor (per-test workspace) and openclaw (pre-configured agents
on each device), hermes agents are created on demand through
``mycelium agent create --adapter hermes``. Hermes uses the
``mycelium-room`` platform plugin — Mycelium rooms only, no Matrix bridge.

Two-phase lifecycle:
  - ``ensure_runtime`` (CommonSetup): creates the agent in the bootstrap
    room once per suite run. Patches ``~/.hermes/config.yaml`` and
    restarts the gateway. Idempotent — skips creation if the handle is
    already present.
  - ``register_in_room`` (per-testcase setup): subscribes the already-
    created agent to the per-scenario room (another ``agent create`` call
    that upserts the room entry in config.yaml + restarts the gateway).
  - ``unregister_from_room`` (per-testcase cleanup): removes the scenario
    room from the agent's subscription list.
  - ``teardown_runtime`` (CommonCleanup): removes the agent from the
    bootstrap room entirely. Skipped for pre-existing agents.

``wake_agent`` is a no-op: the hermes plugin polls coordination sessions
and auto-attends, so no Matrix DM or invoke call is needed.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from libs import host_exec
from libs.host_exec import HostExecError
from libs.provisioners.base import HERMES_BOOTSTRAP_ROOM, ABCProvisioner, AgentRef, PrereqMissing

log = logging.getLogger(__name__)


class HermesProvisioner(ABCProvisioner):
    """Provisioner for the hermes adapter."""

    name: ClassVar[str] = "hermes"
    # Hermes agents are named (alpha-he, beta-he, …); a discovered agent with a
    # different handle must NOT be silently substituted for the spec handle — the
    # handle is threaded through session-join and tick routing so a mismatch
    # causes the wrong agent to receive ticks (or no agent at all).
    requires_exact_handle: ClassVar[bool] = True

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

    def ensure_runtime(
        self,
        device: Any,
        handle: str,
        *,
        bootstrap_room: str = HERMES_BOOTSTRAP_ROOM,
        **kwargs: Any,  # noqa: ARG002
    ) -> AgentRef:
        """Idempotently ensure the hermes agent exists in ``bootstrap_room``.

        Checks ``mycelium agent ls --room <bootstrap_room>``; if the handle
        is already present, returns a ref tagged ``pre_existing=True`` and
        skips creation (no gateway restart).  Otherwise runs
        ``mycelium agent create <handle> --adapter hermes --room
        <bootstrap_room>``, which patches ``~/.hermes/config.yaml``; the
        infra ``restart-hermes-gateway.sh`` reloads the supervisord-managed
        gateway so new room subscriptions take effect.

        By running this in ``CommonSetup`` we avoid the previous pattern
        where per-testcase ``register_in_room`` triggered a gateway restart
        on each scenario's setup — racing with the immediately-following
        ``session_create`` call.
        """
        device_label = host_exec.describe(device)
        log.info("hermes.ensure_runtime: %s on %s", handle, device_label)

        self.ensure_bootstrap_room(device, bootstrap_room)

        existing = self._list_agents_in_room(device, bootstrap_room)
        if handle in existing:
            log.info(
                "hermes.ensure_runtime: %s already present in %s on %s — skipping create",
                handle,
                bootstrap_room,
                device_label,
            )
            return AgentRef(
                handle=handle,
                adapter=self.name,
                device_name=getattr(device, "name", None) or device_label,
                metadata={"bootstrap_room": bootstrap_room, "pre_existing": True},
            )

        log.info(
            "hermes.ensure_runtime: creating %s in %s on %s",
            handle,
            bootstrap_room,
            device_label,
        )
        result = host_exec.execute(
            device,
            ["mycelium", "agent", "create", handle, "--adapter", "hermes", "--room", bootstrap_room],
            timeout=60.0,
        )
        if result.returncode != 0:
            raise PrereqMissing(
                f"hermes: `mycelium agent create {handle} --room {bootstrap_room}` failed "
                f"(rc={result.returncode}): "
                f"{result.stderr.strip()[:300] or result.stdout.strip()[:300]}"
            )
        self._restart_hermes_gateway(device)
        return AgentRef(
            handle=handle,
            adapter=self.name,
            device_name=getattr(device, "name", None) or device_label,
            metadata={"bootstrap_room": bootstrap_room, "pre_existing": False},
        )

    def discover_available(
        self,
        device: Any,
        *,
        bootstrap_room: str = HERMES_BOOTSTRAP_ROOM,
    ) -> list[AgentRef]:
        """Return hermes agents already present in ``bootstrap_room``.

        Hermes agents poll coordination sessions autonomously via the
        mycelium-room plugin — no gateway ping is needed. Being listed
        in the bootstrap room is sufficient evidence of availability.
        """
        device_label = host_exec.describe(device)
        handles = self._list_agents_in_room(device, bootstrap_room)
        if not handles:
            log.debug("hermes.discover_available: no agents in %s on %s", bootstrap_room, device_label)
            return []

        refs = [
            AgentRef(
                handle=h,
                adapter=self.name,
                device_name=getattr(device, "name", None) or device_label,
                metadata={"bootstrap_room": bootstrap_room, "pre_existing": True},
            )
            for h in sorted(handles)
        ]
        log.info(
            "hermes.discover_available: %d agent(s) on %s: %s",
            len(refs),
            device_label,
            [r.handle for r in refs],
        )
        return refs

    def _restart_hermes_gateway(self, device: Any) -> None:
        """Signal the supervisord-managed hermes gateway to reload config."""
        try:
            host_exec.execute(device, ["/openclaw/restart-hermes-gateway.sh"], timeout=20.0)
        except HostExecError as exc:
            log.warning(
                "hermes: gateway restart failed on %s: %s",
                host_exec.describe(device),
                exc,
            )

    def _list_agents_in_room(self, device: Any, room: str) -> set[str]:
        """Return the set of agent handles registered in ``room``.

        Returns an empty set on any failure — callers treat "not present"
        as "needs creating", which is the safe direction.
        """
        try:
            result = host_exec.execute(device, ["mycelium", "agent", "ls", "--room", room], timeout=15.0)
        except HostExecError:
            return set()
        if result.returncode != 0:
            return set()
        handles: set[str] = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("no agents"):
                continue
            # `mycelium agent ls` renders a Rich table:
            #   hermes-agents — agents       ← title (room name, NOT a handle)
            #   ┏━━━━━┳━━━━━━━┓
            #   ┃ Handle … ┃   ← column header
            #   ┡━━━━━╇━━━━━━━┩
            #   │ @alpha-he │ hermes │ …  ← data row: handle is 2nd token
            #   └────┴───────┘
            # Only data rows have "│ @<handle>" shape; skip everything else.
            tokens = line.split()
            if len(tokens) >= 2 and tokens[0] == "│" and tokens[1].startswith("@"):
                handles.add(tokens[1][1:])  # strip leading @
        return handles

    def register_in_room(
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,  # noqa: ARG002 - hermes opening is set at session join
    ) -> AgentRef:
        """Subscribe an already-provisioned hermes agent to a scenario room.

        ``ensure_runtime`` already created the agent in the bootstrap room.
        This call patches ``~/.hermes/config.yaml`` to add ``room`` to that
        agent's subscription list and restarts the gateway (via infra script)
        so the plugin starts polling the new room. The gateway restart takes
        ~7s per host.
        """
        log.info(
            "hermes.register_in_room: %s on %s → %s",
            handle,
            host_exec.describe(device),
            room,
        )
        result = host_exec.execute(
            device,
            ["mycelium", "agent", "create", handle, "--adapter", "hermes", "--room", room],
            timeout=60.0,
        )
        if result.returncode != 0:
            raise PrereqMissing(
                f"hermes: room subscription for {handle} → {room} failed "
                f"(rc={result.returncode}): "
                f"{result.stderr.strip()[:300] or result.stdout.strip()[:300]}"
            )
        self._restart_hermes_gateway(device)
        return AgentRef(
            handle=handle,
            adapter=self.name,
            device_name=getattr(device, "name", None) or str(device),
            metadata={"room": room},
        )

    def unregister_from_room(
        self,
        device: Any,
        agent: AgentRef,
        room: str,
    ) -> None:
        """Remove the agent's subscription from ``room`` (does NOT destroy the runtime)."""
        log.info(
            "hermes.unregister_from_room: %s on %s from %s",
            agent.handle,
            host_exec.describe(device),
            room,
        )
        try:
            result = host_exec.execute(
                device,
                ["mycelium", "agent", "rm", agent.handle, "--room", room, "--force"],
                timeout=60.0,
            )
        except HostExecError as exc:
            log.warning("hermes.unregister_from_room: dispatch failed: %s", exc)
            return
        if result.returncode != 0:
            log.warning(
                "hermes.unregister_from_room: agent rm %s from %s failed (rc=%d): %s",
                agent.handle,
                room,
                result.returncode,
                result.stderr.strip()[:200],
            )

    # ── teardown ──────────────────────────────────────────────────────

    def teardown_runtime(self, device: Any, agent: AgentRef) -> None:
        """Remove the hermes agent from its bootstrap room.

        Skipped when the agent was pre-existing — we didn't create it
        so we don't own its lifecycle.
        """
        if agent.metadata.get("pre_existing"):
            log.info(
                "hermes.teardown_runtime: %s was pre-existing; leaving alone",
                agent.handle,
            )
            return

        bootstrap_room = agent.metadata.get("bootstrap_room") or HERMES_BOOTSTRAP_ROOM
        log.info(
            "hermes.teardown_runtime: removing %s from %s on %s",
            agent.handle,
            bootstrap_room,
            host_exec.describe(device),
        )
        try:
            result = host_exec.execute(
                device,
                ["mycelium", "agent", "rm", agent.handle, "--room", bootstrap_room, "--force"],
                timeout=60.0,
            )
        except HostExecError as exc:
            log.warning("hermes.teardown_runtime: dispatch failed for %s: %s", agent.handle, exc)
            return
        if result.returncode != 0:
            log.warning(
                "hermes.teardown_runtime: agent rm %s failed (rc=%d): %s",
                agent.handle,
                result.returncode,
                result.stderr.strip()[:200],
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
