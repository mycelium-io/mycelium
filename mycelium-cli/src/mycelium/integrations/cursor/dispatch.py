# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Cursor dispatch facet — manifest IS the registration (same shape as claude_code).

Cursor agents are cold-spawned by the cc-daemon: every ``@handle`` mention
fires a fresh ``cursor-agent -p`` in the manifest's ``cwd`` (Cursor's workspace
root). So register/destroy have no external runtime to wire up — they only
claim/release the handle in ``cc-daemon.toml`` so two daemons subscribed to
the same room don't both dispatch.

The install facet methods land in :mod:`mycelium.integrations.cursor.install`
(cursor-pkg milestone). The actual ``cursor-agent -p`` invocation lands in
:mod:`mycelium.integrations.cursor.spawn` (cursor-cli milestone). This module
exists at the protocol milestone so the registry has a real :class:`Integration`
to return for ``adapter == "cursor"`` — without it, every
:func:`get_integration("cursor")` call would crash and the contract test
couldn't be parametrised over the family.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from mycelium.integrations._spawn_common import SpawnRequest, SpawnResult
from mycelium.integrations.base import AddOptions, Integration
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class CursorIntegration(Integration):
    name = "cursor"
    lifecycle = "cold_spawn"

    #: Follow-up ``mycelium adapter add cursor --step=<name>`` actions. Filled
    #: in by :mod:`mycelium.integrations.cursor.install` (cursor-pkg) — the
    #: ``daemon`` step composes :mod:`mycelium.daemon.install` like
    #: ``claude_code`` does.
    STEPS: dict[str, str] = {}

    def __init__(self, *, cwd: str | None = None) -> None:
        # Same shape as ClaudeCodeIntegration: cwd is the one family-specific
        # ``agent add`` flag and is threaded in at construction so
        # ``build_manifest`` keeps a uniform signature across families.
        self._cwd = cwd

    # ── dispatch facet ──────────────────────────────────────────────────────

    def build_manifest(
        self,
        *,
        handle: str,
        opts: AddOptions,
        description: str,
        budget: float,
        allow_from: list[str],
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="cursor",
            cwd=self._cwd,
            description=description,
            budget_usd_per_month=budget,
            allow_from=allow_from,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # Identical ownership semantics to claude_code: a cursor agent is
        # cold-spawned by THIS machine's cc-daemon (its cwd is local). Claim
        # the handle in cc-daemon.toml so a sibling daemon that syncs this
        # room via git does NOT also dispatch — without ownership two
        # cursor-agent processes would race over the same cwd.
        from mycelium.daemon.config import DaemonConfig

        daemon_cfg = DaemonConfig.load()
        if daemon_cfg.own_handle(manifest.handle):
            daemon_cfg.save()

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # No external runtime to tear down. ``full`` is meaningless here — the
        # only artifacts are the manifest (deleted by the command layer) and
        # notes/logs (deliberately preserved). Release the cc-daemon ownership
        # claimed in :meth:`register`.
        from mycelium.daemon.config import DaemonConfig

        daemon_cfg = DaemonConfig.load()
        if daemon_cfg.disown_handle(manifest.handle):
            daemon_cfg.save()

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        lines = [
            f"  adapter: {manifest.adapter}",
            f"  cwd:     {manifest.cwd}",
        ]
        if manifest.allow_from:
            lines.append(f"  allow:   {', '.join(manifest.allow_from)}")
        lines.append(
            "\n[dim]Seed the agent's brain (optional):[/dim]\n"
            f'  mycelium memory set {manifest.notes_key} "..." --room {room}\n'
            "[dim]Make sure the daemon watches this room:[/dim]\n"
            f"  mycelium daemon subscribe {room}\n"
            "[dim]Then invoke it:[/dim]\n"
            f'  mycelium agent invoke {manifest.handle} "..."'
        )
        return lines

    # ── cold-spawn dispatch ─────────────────────────────────────────────────

    async def spawn(self, *, request: SpawnRequest) -> SpawnResult:
        """Cold-spawn ``cursor-agent -p`` for one ``@handle`` mention.

        Stub until the ``cursor-cli`` milestone wires
        :mod:`mycelium.integrations.cursor.spawn`. Overrides
        :meth:`Integration.spawn` so the contract test
        ``test_spawn_override_matches_lifecycle`` passes; the daemon dispatch
        loop will still call this and surface the raise verbatim in the
        invocation log if anyone tries to ``@-mention`` a cursor agent before
        the CLI is wired (the agent create wizard refuses to create cursor
        manifests at the wizard milestone unless ``cursor-agent`` is on PATH).
        """
        raise NotImplementedError(
            "cursor spawn not wired yet — landing in the cursor-cli milestone "
            "(mycelium.integrations.cursor.spawn)"
        )

    # ── install facet (stubs — implemented in the cursor-pkg milestone) ─────
    #
    # NotImplementedError stubs satisfy ``Integration``'s @abstractmethod
    # contract (and ``test_integration_contract.test_install_facet_is_implemented``)
    # without pretending cursor's host install is done. The command layer in
    # ``commands/adapter.py`` resolves through ``get_integration`` and will
    # surface the raise verbatim — that's the intended UX until cursor-pkg
    # lands the real implementations alongside the .cursor/rules/mycelium.mdc
    # and AGENTS.md assets.

    def install(
        self,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,
        container: str | None,
        reinstall: bool,
    ) -> None:
        raise NotImplementedError(
            "cursor install not wired yet — landing in the cursor-pkg milestone"
        )

    def uninstall(self, *, record: dict, profile: str | None, container: str | None) -> None:
        # No external runtime ever — same semantics as claude_code. Real
        # implementation in cursor-pkg deletes assets the install dropped.
        return

    def reinstall_targets(self, *, profile: str | None, container: str | None) -> list[str]:
        # Real list lands in cursor-pkg — pointing at <cwd>/.cursor/rules/
        # mycelium.mdc + <cwd>/AGENTS.md.
        return []

    def dry_run_lines(
        self, *, config: MyceliumConfig, profile: str | None, container: str | None
    ) -> list[str]:
        return ["  (cursor install not wired yet — see cursor-pkg milestone)"]

    def post_install_banner(
        self,
        *,
        config: MyceliumConfig,
        reinstall: bool,
        profile: str | None,
        container: str | None,
    ) -> None:
        typer.secho(
            "Adapter 'cursor' install not wired yet — see cursor-pkg milestone.",
            fg=typer.colors.YELLOW,
        )

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
        raise NotImplementedError(
            f"cursor --step={step} not wired yet — landing in the cursor-pkg milestone"
        )

    def status_check(self, *, name: str, info: dict) -> dict:
        # The shape ``{ok, details}`` is what ``mycelium adapter status``
        # consumes — keeping it valid avoids a UI crash on listing installed
        # adapters before cursor-pkg lands. ``ok=False`` is the truthful
        # answer: nothing's actually been installed.
        return {
            "ok": False,
            "details": [
                "  ✗ cursor install not wired yet (see cursor-pkg milestone)",
                f"api_url: {info.get('api_url', '')}",
            ],
        }


#: Back-compat alias for the historical class-name convention.
CursorAdapter = CursorIntegration
