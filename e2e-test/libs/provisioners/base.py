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
    """

    name: ClassVar[str]

    def check_prereqs(self, device: Any) -> None:
        """Raise :class:`PrereqMissing` if this adapter is not installed
        on ``device`` (e.g. cursor-agent binary absent, hermes-gateway
        not running). Scenarios convert ``PrereqMissing`` to
        ``self.skipped(...)`` so missing adapters are visible but
        non-fatal."""

    def create_agent(
        self,
        device: Any,
        handle: str,
        room: str,
        *,
        opening: str | None = None,
    ) -> AgentRef:
        """Register an agent on ``device`` and subscribe it to ``room``.

        Must be idempotent: re-running with the same ``handle`` should
        succeed and yield the same ref.
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

    def cleanup_agent(
        self,
        device: Any,
        agent: AgentRef,
        room: str,
    ) -> None:
        """Tear down the agent and any per-test artefacts (workspace,
        session files, etc.). Must be safe to call even if creation
        partially failed."""
