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
the old reserved ``ALIGNER_HANDLE``), so ``lifecycle="backend_engine"``. There are
no host-side assets — hence the no-op install/register facets.
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
        allow_from: list[str],
        owner: str | None = None,
        team: str | None = None,
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="engine",
            kind=self._kind,
            description=description,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # No runtime side effects — the backend owns an engine's run via its
        # summon seam. The manifest (persisted by the command layer) is the whole
        # registration.
        return

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # No host assets and no runtime mycelium started; nothing to tear down.
        return

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
