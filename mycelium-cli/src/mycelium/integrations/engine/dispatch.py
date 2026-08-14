# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The ``engine`` integration — mycelium's *first-party* cognition-engine family.

Unlike ``claude_code`` / ``cursor`` (which bridge to a
*third-party* runtime we don't own), an engine is **ours**: our NEGMAS loop, our
brain. One ``engine`` family hosts a variety of Cognition Engines, selected by
the manifest's ``kind`` (``aligner`` today; ``bargainer``, ``team_former``, a
drift evaluator later) — the extensibility axis, no new adapter per CE.

An engine is a first-class registered *room citizen* — a manifest at
``agents/<handle>`` (``adapter="engine"``, ``kind=<ce>``), listed by
``engine ls`` / ``agent ls``, invokable, posting as itself. Its run is owned
by the **backend's summon seam** (which recognises registered engines instead of
the old reserved ``ALIGNER_HANDLE``), so ``lifecycle="backend_engine"`` and the
daemon skips it. There are no host-side assets — hence the no-op install facet.
The host-side runtime path (``engine.runtime = host``) drives NEGMAS + Pi brain
under the local daemon instead; see ``mycelium.integrations.engine.host``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from mycelium.integrations.base import AddOptions, Integration
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class EngineIntegration(Integration):
    name = "engine"
    lifecycle = "backend_engine"

    def __init__(self, *, kind: str | None = None) -> None:
        # ``kind`` is the one engine-specific ``engine create`` flag, threaded in
        # at construction so ``build_manifest`` keeps a uniform signature across
        # families (same shape as ``cwd`` for claude_code).
        self._kind = kind

    # ── dispatch facet ──────────────────────────────────────────────────────

    def build_manifest(
        self,
        *,
        handle: str,
        opts: AddOptions,
        description: str,
        budget: float,
        allow_from: list[str],
        owner: str | None = None,
        team: str | None = None,
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="engine",
            kind=self._kind,
            description=description,
            budget_usd_per_month=budget,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # Claim the handle in daemon.toml (same as a cold_spawn agent). Under
        # ``engine.runtime = backend`` this is inert — ``connector_targets``
        # skips ``backend_engine`` manifests — but with ``engine.runtime = host``
        # it's what makes the local daemon hold the engine's connector and drive
        # NEGMAS on the host. Claiming it always keeps the flip to host a pure
        # config change, and prevents a second machine syncing the room from also
        # owning the engine.
        from mycelium.daemon.config import DaemonConfig

        daemon_cfg = DaemonConfig.load()
        if daemon_cfg.own_handle(manifest.handle):
            daemon_cfg.save()

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # Release the daemon ownership claimed in register(); nothing else to
        # tear down (no host assets).
        from mycelium.daemon.config import DaemonConfig

        daemon_cfg = DaemonConfig.load()
        if daemon_cfg.disown_handle(manifest.handle):
            daemon_cfg.save()

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        lines = [
            f"  adapter: {manifest.adapter}",
            f"  kind:    {manifest.kind}",
        ]
        if manifest.allow_from:
            lines.append(f"  allow:   {', '.join(manifest.allow_from)}")
        lines.append(
            "\n[dim]Seed the engine's brain (optional):[/dim]\n"
            f'  mycelium memory set {manifest.notes_key} "..." --room {room}\n'
            "[dim]Make sure the backend watches this room, then summon it:[/dim]\n"
            f'  mycelium engine invoke {manifest.handle} "..."'
        )
        return lines

    # ── install facet (no host assets — engines are backend-run) ─────────────

    def install(
        self,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,
        container: str | None,
        reinstall: bool,
    ) -> None:
        return

    def uninstall(self, *, record: dict, profile: str | None, container: str | None) -> None:
        return

    def reinstall_targets(self, *, profile: str | None, container: str | None) -> list[str]:
        return []

    def dry_run_lines(
        self, *, config: MyceliumConfig, profile: str | None, container: str | None
    ) -> list[str]:
        return ["  (no host-level install for engines — the backend runs them)"]

    def post_install_banner(
        self,
        *,
        config: MyceliumConfig,
        reinstall: bool,
        profile: str | None,
        container: str | None,
    ) -> None:
        typer.secho("Engine family ready.", fg=typer.colors.GREEN)
        typer.echo("  Create a cognition engine in a room:")
        typer.secho(
            "    $ mycelium engine create <handle> --kind aligner --room <room>",
            fg=typer.colors.CYAN,
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
        return

    def status_check(self, *, name: str, info: dict) -> dict:
        # Engines have no host binary/asset to probe; the backend owns their run.
        return {"ok": True, "details": [f"api_url: {info.get('api_url', '')}"]}
