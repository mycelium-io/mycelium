# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
AgentAdapter — the lifecycle contract for hosting a Mycelium agent.

An agent is always a manifest under ``agents/<handle>``. What *makes it live*
differs per runtime:

- ``claude_code`` — nothing extra. The cc-daemon discovers manifests off the
  filesystem and dispatches ``@handle`` mentions to ``claude -p`` spawns. The
  manifest *is* the registration.
- ``openclaw`` — the agent runs inside the OpenClaw gateway. Registration
  means creating/adopting the OpenClaw agent and wiring it into the
  mycelium-room channel's per-room fan-out, then restarting the gateway.

The command layer (``commands/agent.py``) stays thin: it resolves the
adapter, builds + persists the manifest, and delegates the runtime side
effects here. Add a new runtime by adding one subclass + registering it in
``__init__.ADAPTERS`` — no churn in the command layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.sstp import AgentManifest


@dataclass
class AddOptions:
    """Adapter-agnostic context for `agent add`.

    Only fields that are meaningful to *every* adapter live here. Adapter-
    specific options (cwd, openclaw_agent, model, copy_auth_from, …) are NOT
    here — they're passed straight to the concrete adapter's constructor via
    ``get_adapter(...)`` and stored on the instance. That keeps this base
    type from accreting one field per adapter as runtimes are added.
    """

    room: str


class AgentAdapter(ABC):
    """Lifecycle for one agent runtime. Stateless — safe to instantiate once."""

    #: Stable adapter id; must match ``AgentManifest.adapter`` literals and
    #: ``sstp.AGENT_ADAPTERS``.
    name: str

    @abstractmethod
    def build_manifest(
        self,
        *,
        handle: str,
        opts: AddOptions,
        description: str,
        budget: float,
        allow_from: list[str],
    ) -> AgentManifest:
        """Construct (and validate) the manifest for this adapter.

        Raises pydantic ValidationError on bad input — the command layer
        catches it and prints a friendly message.
        """

    @abstractmethod
    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        """Make the agent live (runtime side effects only).

        Called BEFORE the manifest is persisted, so a failure here aborts the
        add without leaving a dangling manifest. No-op adapters just pass.
        """

    @abstractmethod
    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        """Reverse :meth:`register`. Called BEFORE the manifest is deleted.

        ``full`` requests destructive teardown of the underlying runtime
        (gated + confirmed in the command layer). Adapters must still refuse
        to destroy resources the user owns (e.g. an adopted OpenClaw agent).
        """

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        """Lines printed after a successful add. Override per adapter."""
        return [f"  adapter: {manifest.adapter}"]

    # ── helpers the command layer uses for confirmation copy ────────────────

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        """True if ``destroy(full=...)`` will irreversibly destroy a runtime
        resource — drives the command layer's confirmation wording."""
        return False
