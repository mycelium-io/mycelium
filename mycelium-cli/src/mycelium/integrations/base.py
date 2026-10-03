# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Integration: the single contract for a runtime family Mycelium integrates with.

Every runtime family is one ``Integration`` subclass exposing the same
contract: build, register and destroy the ``agents/<handle>`` manifest.
Adding a capability to one family without the others surfaces as an
abstract-method gap (and a failing ``tests/test_integration_contract.py``),
not a silent degradation.

The command layer (``commands/agent.py``, ``commands/engine.py``,
``commands/swarm.py``) stays thin: resolve the integration via
:func:`mycelium.integrations.get_integration`, then call it. Add a runtime by
adding one subclass + registering it in ``integrations.__init__.INTEGRATIONS``,
no churn in the command layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.protocol import AgentManifest


#: Discriminator for *where* this family's agents run: the liveness distinction
#: the UI/tooling surface (backend-hosted vs. user/herdr runtime).
#:
#: - ``resident``: the agent runs in a user-owned (or herdr-managed) runtime that
#:   participates via ``mycelium await``/``respond``, e.g. a Claude Code or Cursor
#:   session, typically kept woken with ``mycelium await --loop``. Mycelium names
#:   the agent; it does not run the process.
#: - ``backend_engine``: a first-party cognition engine (``adapter="engine"``)
#:   whose run the **backend** owns via its summon seam. With
#:   ``engine.runtime = host`` the engine instead runs as a host-side runtime.
LifecycleModel = Literal["resident", "backend_engine"]


@dataclass
class AddOptions:
    """Adapter-agnostic context for `agent add`.

    Only fields that are meaningful to *every* integration live here. Family-
    specific options (cwd, …) are NOT
    here; they're passed straight to the concrete integration's constructor
    via ``get_integration(...)`` and stored on the instance. That keeps this
    base type from accreting one field per family as runtimes are added.
    """

    room: str


class Integration(ABC):
    """Lifecycle for one agent runtime family. Stateless, safe to instantiate."""

    #: Canonical family id: must match the ``AgentManifest.adapter`` literals,
    #: ``sstp.AGENT_ADAPTERS``, and the ``integrations.INTEGRATIONS`` registry
    #: key. Always the underscore spelling (``claude_code``), since that is the
    #: value persisted in ``agents/<handle>`` manifests.
    name: str

    #: Where this family's agents run (``resident`` vs ``backend_engine``): the
    #: liveness distinction surfaced to tooling/UI. Every subclass MUST declare a
    #: value; ``tests/test_integration_contract`` enforces this.
    lifecycle: ClassVar[LifecycleModel]

    @abstractmethod
    def build_manifest(
        self,
        *,
        handle: str,
        opts: AddOptions,
        description: str,
        allow_from: list[str],
        owner: str | None = None,
        team: str | None = None,
    ) -> AgentManifest:
        """Construct (and validate) the manifest for this family.

        ``owner`` / ``team`` are the self-asserted principal binding: the
        ``users/<handle>`` this agent belongs to and the team it's fielded by.
        Both default to ``None`` (principal-anonymous).

        Raises pydantic ValidationError on bad input; the command layer
        catches it and prints a friendly message.
        """

    @abstractmethod
    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        """Make the agent live (runtime side effects only).

        Called BEFORE the manifest is persisted, so a failure here aborts the
        add without leaving a dangling manifest. No-op families just pass.
        """

    @abstractmethod
    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        """Reverse :meth:`register`. Called BEFORE the manifest is deleted.

        ``full`` requests destructive teardown of the underlying runtime
        (gated + confirmed in the command layer). Integrations must still
        refuse to destroy resources the user owns.
        """

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        """Lines printed after a successful add. Override per family."""
        return [f"  adapter: {manifest.adapter}"]

    # ── helpers the command layer uses for confirmation copy ────────────────

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        """True if ``destroy(full=...)`` will irreversibly destroy a runtime
        resource; drives the command layer's confirmation wording."""
        return False


#: Readability alias: the contract reads naturally as an "adapter" at some
#: call sites. (The historical ``mycelium.agent_adapters`` package has been
#: removed; this is the one concept now.)
AgentAdapter = Integration
