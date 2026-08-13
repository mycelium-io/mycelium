# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Integration — the single contract for a runtime family Mycelium integrates with.

Every runtime family is one ``Integration`` subclass exposing the same
facets, giving a unified dispatch/install contract. Adding a capability to one
family without the others surfaces as an abstract-method gap (and a
failing ``tests/test_integration_contract.py``), not a silent degradation.

An integration has two facets, sliced by lifetime:

- **Dispatch facet** (per-agent): build/register/destroy the ``agents/<handle>``
  manifest and produce a reply for an ``@handle`` mention. Implemented here in
  Stage 1.
- **Install facet** (per-host, one-time): stage assets / wire hooks / plugin /
  service into the runtime, reversible, plus follow-up ``--step`` actions. The
  abstract surface lands with the install relocation (Stage 2); see
  ``integrations/<family>/install.py``.

The command layer (``commands/agent.py``, ``commands/adapter.py``) stays thin:
resolve the integration via :func:`mycelium.integrations.get_integration`, then
call the relevant facet. Add a runtime by adding one subclass + registering it
in ``integrations.__init__.INTEGRATIONS`` — no churn in the command layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.integrations._spawn_common import SpawnRequest, SpawnResult
    from mycelium.protocol import AgentManifest


#: Discriminator for how this family's agents come into existence per mention.
#:
#: - ``cold_spawn``: the daemon spawns a fresh process per mention
#:   (``claude -p``, ``cursor-agent -p``, future Gemini/Codex/Aider). The
#:   family overrides :meth:`Integration.spawn`.
#: - ``long_lived_gateway``: agents live inside a separate, long-running runtime
#:   that owns its own mention delivery. The daemon ignores these manifests
#:   entirely — the gateway is responsible for dispatch. (No first-party family
#:   uses this today; retained as a lifecycle seam.)
#: - ``backend_engine``: a first-party cognition engine (``adapter="engine"``)
#:   whose run the **backend** owns via its summon seam. The daemon skips these,
#:   same as a gateway. With ``engine.runtime = host`` the engine instead runs
#:   as a host-side runtime under the local daemon.
LifecycleModel = Literal["cold_spawn", "long_lived_gateway", "backend_engine"]


@dataclass
class AddOptions:
    """Adapter-agnostic context for `agent add`.

    Only fields that are meaningful to *every* integration live here. Family-
    specific options (cwd, …) are NOT
    here — they're passed straight to the concrete integration's constructor
    via ``get_integration(...)`` and stored on the instance. That keeps this
    base type from accreting one field per family as runtimes are added.
    """

    room: str


class Integration(ABC):
    """Lifecycle for one agent runtime family. Stateless — safe to instantiate.

    Subclasses currently implement the **dispatch facet** (below). The
    **install facet** is added in the install relocation; see the module
    docstring and ``integrations/<family>/install.py``.
    """

    #: Canonical family id — must match the ``AgentManifest.adapter`` literals,
    #: ``sstp.AGENT_ADAPTERS``, and the ``integrations.INTEGRATIONS`` registry
    #: key. Always the underscore spelling (``claude_code``), since that is the
    #: value persisted in ``agents/<handle>`` manifests.
    name: str

    #: How this family delivers mentions to its agents — drives whether the
    #: daemon dispatch loop calls :meth:`spawn` on this family or skips it.
    #: Every subclass MUST declare a value; ``tests/test_integration_contract``
    #: enforces this.
    lifecycle: ClassVar[LifecycleModel]

    #: Follow-up ``mycelium adapter add <family> --step=<name>`` actions this
    #: family supports, mapped to a one-line description. Empty = no steps.
    STEPS: dict[str, str] = {}

    # ── install facet (per-host) ────────────────────────────────────────────
    #
    # The host-level install/uninstall/step/status surface. The typer command
    # (`commands/adapter.py`) is a thin dispatcher: it resolves the integration
    # via ``get_integration`` and calls these — there is no ``if family ==``
    # branching left. ``profile`` / ``container`` are legacy gateway knobs
    # carried on the signature for uniformity; families that ignore them just
    # don't read them.

    @abstractmethod
    def install(
        self,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,
        container: str | None,
        reinstall: bool,
    ) -> None:
        """Install/redeploy this family's host assets (the base ``add``)."""

    @abstractmethod
    def uninstall(
        self,
        *,
        record: dict,
        profile: str | None,
        container: str | None,
    ) -> None:
        """Reverse :meth:`install` (the ``remove`` command). No-op families pass."""

    @abstractmethod
    def reinstall_targets(self, *, profile: str | None, container: str | None) -> list[str]:
        """Paths a ``--reinstall`` would overwrite — drives the confirm prompt."""

    @abstractmethod
    def dry_run_lines(
        self, *, config: MyceliumConfig, profile: str | None, container: str | None
    ) -> list[str]:
        """Lines printed under ``[dry-run]`` (the family-specific plan)."""

    @abstractmethod
    def post_install_banner(
        self,
        *,
        config: MyceliumConfig,
        reinstall: bool,
        profile: str | None,
        container: str | None,
    ) -> None:
        """Print the family's post-install "next steps" banner."""

    @abstractmethod
    def run_step(
        self,
        step: str,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,
        container: str | None,
        remove: bool,
    ) -> None:
        """Run (or, with ``remove``, reverse) a ``--step`` follow-up action."""

    @abstractmethod
    def status_check(self, *, name: str, info: dict) -> dict:
        """Health-check a registered install. Returns ``{ok: bool, details: [str]}``."""

    # ── dispatch facet (per-agent) ──────────────────────────────────────────

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
        """Construct (and validate) the manifest for this family.

        Raises pydantic ValidationError on bad input — the command layer
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

    # ── cold-spawn dispatch (per-mention) ───────────────────────────────────

    async def spawn(self, *, request: SpawnRequest) -> SpawnResult:
        """Cold-spawn this family for one ``@handle`` mention.

        Every ``lifecycle == "cold_spawn"`` family MUST override this. Long-
        lived gateway families inherit this raise — the daemon dispatch loop
        checks ``lifecycle`` before calling and never invokes ``spawn`` on a
        gateway family, so the raise is a safety net for bugs in routing.

        Why not :func:`@abstractmethod`: forcing every long-lived-gateway
        family to declare a no-op stub buys no safety (the contract test
        enforces override on cold_spawn families directly) and adds
        boilerplate to every future gateway integration.
        """
        raise NotImplementedError(
            f"{type(self).__name__} (lifecycle={getattr(self, 'lifecycle', '?')}) "
            "does not support cold-spawn dispatch"
        )

    # ── helpers the command layer uses for confirmation copy ────────────────

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        """True if ``destroy(full=...)`` will irreversibly destroy a runtime
        resource — drives the command layer's confirmation wording."""
        return False


#: Readability alias — the contract reads naturally as an "adapter" at some
#: call sites. (The historical ``mycelium.agent_adapters`` package has been
#: removed; this is the one concept now.)
AgentAdapter = Integration
