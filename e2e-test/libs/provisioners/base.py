"""Adapter-agnostic provisioner protocol.

Every scenario in :mod:`testcases.scenarios` is parameterised by an
``agents`` list whose entries declare ``adapter`` ("openclaw" | "cursor" |
"hermes") and ``host`` (a logical device name in the active testbed).
For each entry the scenario looks up a :class:`Provisioner` via
:func:`libs.provisioners.get_provisioner` and uses it to create, wake and
clean up the underlying agent.

The protocol intentionally takes a pyATS ``Device`` directly (rather than
a bespoke ``HostRef``): the device's ``custom.transport`` already tells
:func:`libs.host_exec.execute` how to dispatch, so provisioner methods
need nothing more than the device handle plus the requested handle/room.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable


class PrereqMissing(RuntimeError):
    """Raised by :meth:`Provisioner.check_prereqs` when the adapter is
    not installed or wired up on the requested device."""


@dataclass
class AgentRef:
    """Handle to an agent created by a provisioner.

    Attributes:
        handle: Mycelium handle (the routing key used by ``mycelium agent
            create`` and inside the matrix datafile).
        adapter: ``"openclaw" | "cursor" | "hermes"``.
        device_name: Logical device name in the active testbed
            (``"hub"`` / ``"spoke1"`` / ``"spoke2"``). Lets cleanup find
            the right device without holding the Device object directly.
        metadata: Adapter-specific bookkeeping. For example, the cursor
            provisioner stores ``workspace_path``; the openclaw
            provisioner stores ``matrix_token_env`` (or None for local).
    """

    handle: str
    adapter: str
    device_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


BOOTSTRAP_ROOM = "matrix-agents"
"""Room used as the holding pen for runtime-provisioned agents.

Openclaw agents must be registered into *some* room when they're
created (the manifest needs a home). We use a stable ``matrix-agents``
room as the bootstrap location so the same agent runtime can be
adopted into per-scenario rooms via ``mycelium agent add`` without
ever being torn down and recreated. The bootstrap room is created
lazily by :meth:`ABCProvisioner.ensure_bootstrap_room` and never
deleted by the scenarios suite — it's the "home" the agents return to.
"""


@runtime_checkable
class Provisioner(Protocol):
    """Adapter-specific lifecycle for a single agent.

    Implementations live in sibling modules (``openclaw.py``,
    ``cursor.py``, ``hermes.py``) and are registered in
    :func:`libs.provisioners.get_provisioner`.

    All methods MUST be safe to call against a freshly-imported pyATS
    Device - implementations call :func:`libs.host_exec.execute` rather
    than touching SSH or docker directly. This keeps the test code free
    of transport details.

    Lifecycle model (post-refactor):

    1. **Suite common_setup:** :meth:`ensure_runtime` runs ONCE per
       unique ``(handle, adapter, host)``. For heavyweight runtimes
       (openclaw spawns a Claude Code instance) this creates the
       underlying account/process and registers a manifest in the
       :data:`BOOTSTRAP_ROOM`. Idempotent.
    2. **Per-testcase setup:** :meth:`register_in_room` adopts the
       already-provisioned agent into the scenario's freshly created
       room. Lightweight (just writes a room manifest).
    3. **Wake:** :meth:`wake_agent` nudges the agent toward the active
       session — Matrix DM (openclaw spokes), ``agent invoke`` (cursor)
       or no-op (hermes).
    4. **Per-testcase cleanup:** :meth:`unregister_from_room` drops
       the per-scenario manifest. The runtime survives.
    5. **Suite common_cleanup (optional):** :meth:`teardown_runtime`
       destroys the runtime entirely. Gated on
       ``MYCELIUM_E2E_KEEP_AGENTS`` so devs iterating on tests don't
       pay the spawn cost every run.

    Legacy :meth:`create_agent` / :meth:`cleanup_agent` survive for
    callers that haven't migrated yet — they map to ``ensure_runtime
    + register_in_room`` and ``unregister_from_room`` respectively.
    """

    name: ClassVar[str]

    def check_prereqs(self, device: Any) -> None:
        """Raise :class:`PrereqMissing` if this adapter is not installed
        on ``device`` (e.g. cursor-agent binary absent, hermes-gateway
        not running). Scenarios convert ``PrereqMissing`` to
        ``self.skipped(...)`` so missing adapters are visible but
        non-fatal."""

    def ensure_runtime(
        self,
        device: Any,
        handle: str,
        *,
        bootstrap_room: str = BOOTSTRAP_ROOM,
        **kwargs: Any,
    ) -> AgentRef:
        """Idempotently create the adapter's runtime-side state.

        For openclaw this spawns the OpenClaw agent at the gateway and
        writes a manifest in ``bootstrap_room``. For cursor/hermes
        this typically does nothing (their runtime is cold-spawned
        per-scenario anyway) — default impl returns a minimal
        :class:`AgentRef`. Must be safe to re-run for an agent that
        already exists.
        """

    def register_in_room(
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,
    ) -> AgentRef:
        """Adopt an already-provisioned agent into ``room``.

        The agent must have been through :meth:`ensure_runtime` first
        (or pre-configured by hand on the device — stage 1). For
        openclaw this is ``mycelium agent add <handle> --room <room>``.
        Cursor/hermes can roll this into their existing per-test
        ``create_agent`` flow.
        """

    def wake_agent(
        self,
        device: Any,
        agent: AgentRef,
        session_room: str,
    ) -> None:
        """Nudge ``agent`` to attend ``session_room``.

        No-op for adapters that auto-attend (hermes plugin polls
        coordination sessions; cursor daemon subscribes to all rooms it
        owns). The openclaw provisioner posts a Matrix DM when the
        device's role is ``"spoke"``.
        """

    def unregister_from_room(
        self,
        device: Any,
        agent: AgentRef,
        room: str,
    ) -> None:
        """Drop the agent's room manifest.

        Must NOT tear down the runtime — that's :meth:`teardown_runtime`'s
        job. Safe to call even if registration partially failed.
        """

    def teardown_runtime(
        self,
        device: Any,
        agent: AgentRef,
    ) -> None:
        """Tear down the adapter's runtime-side state created by
        :meth:`ensure_runtime`.

        For openclaw this destroys the OpenClaw agent + workspace.
        Cursor/hermes default to no-op since they don't carry
        cross-scenario runtime state.
        """

    # ── legacy adapters (forwarding shims) ────────────────────────────

    def create_agent(
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,
    ) -> AgentRef:
        """Legacy one-shot: ``ensure_runtime`` + ``register_in_room``.

        Kept for callers that haven't moved to the two-phase
        lifecycle. New code should call the two methods separately so
        the heavy work lives in suite ``common_setup``.
        """

    def cleanup_agent(
        self,
        device: Any,
        agent: AgentRef,
        room: str,
    ) -> None:
        """Legacy: ``unregister_from_room`` (does NOT call
        ``teardown_runtime``). New tests should call those two
        methods explicitly so runtime teardown is centralised in
        ``common_cleanup`` and can be skipped for iterative debug
        runs."""


class ABCProvisioner:
    """Mixin base class with default implementations.

    Concrete provisioners inherit from this AND declare ``name`` to
    satisfy the :class:`Provisioner` protocol. The defaults forward
    legacy calls to the new two-phase methods, so existing
    ``create_agent``/``cleanup_agent`` overrides keep working until
    they migrate.
    """

    name: ClassVar[str] = "abc"

    def check_prereqs(self, device: Any) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    # Default ensure_runtime is a no-op: returns a minimal AgentRef
    # so cursor/hermes (which don't need pre-spawn) work out of the
    # box without each concrete class repeating the boilerplate.
    def ensure_runtime(
        self,
        device: Any,
        handle: str,
        *,
        bootstrap_room: str = BOOTSTRAP_ROOM,  # noqa: ARG002 - kept for API parity
        **kwargs: Any,  # noqa: ARG002
    ) -> AgentRef:
        return AgentRef(
            handle=handle,
            adapter=self.name,
            device_name=getattr(device, "name", None) or str(device),
            metadata={"runtime": "no-op"},
        )

    def register_in_room(  # pragma: no cover - abstract for non-default cases
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,
    ) -> AgentRef:
        # Default forwards to legacy ``create_agent`` so subclasses
        # that haven't migrated keep working. Migrated subclasses
        # override this directly.
        return self.create_agent(device, handle, room, opening=opening)

    def wake_agent(self, device: Any, agent: AgentRef, session_room: str) -> None:
        # Default is a no-op (hermes/cursor pattern). Openclaw
        # overrides to send Matrix DMs to spoke agents.
        return None

    def unregister_from_room(self, device: Any, agent: AgentRef, room: str) -> None:
        # Default forwards to legacy ``cleanup_agent`` for the same
        # backward-compat reason as register_in_room.
        self.cleanup_agent(device, agent, room)

    def teardown_runtime(self, device: Any, agent: AgentRef) -> None:  # noqa: ARG002
        # Default no-op: cursor/hermes don't have a runtime to tear
        # down. Openclaw overrides this to destroy the OpenClaw agent.
        return None

    # Legacy methods — concrete classes that pre-date the two-phase
    # split implement these directly; the defaults above forward back
    # so either flavour of subclass keeps working.

    def create_agent(  # pragma: no cover - abstract
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,
    ) -> AgentRef:
        raise NotImplementedError(f"{self.name}: override either create_agent OR ensure_runtime+register_in_room")

    def cleanup_agent(self, device: Any, agent: AgentRef, room: str) -> None:  # noqa: ARG002
        # Default cleanup is a noop — concrete classes override this
        # (or unregister_from_room) for state that needs teardown.
        return None
