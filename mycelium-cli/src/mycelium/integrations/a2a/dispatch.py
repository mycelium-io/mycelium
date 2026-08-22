# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The ``a2a`` integration: an *external* Agent2Agent endpoint as a room member.

Unlike ``engine`` (our own cognition) or ``claude_code``/``cursor`` (a resident
third-party session on the user's box), an ``a2a`` agent is a remote endpoint
that speaks the Agent2Agent protocol. The backend resolves its Agent Card and
holds the seat that calls it, so — like an engine — ``lifecycle="backend_engine"``
and there are no host-side assets (no-op install/register facets).

Registration differs from the other families in one way: the card must be
resolved on the hub (the thin CLI has no A2A client), so ``agent create
--adapter a2a --card <url>`` posts to the backend's ``a2a-agents`` route rather
than building the manifest locally. This class exists so ``a2a`` is a first-class
family everywhere the registry is the source of truth (``agent ls``, manifest
parsing, the integration contract).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from mycelium.integrations.base import AddOptions, Integration
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class A2aIntegration(Integration):
    name = "a2a"
    lifecycle = "backend_engine"

    def __init__(self, *, card: str | None = None) -> None:
        # ``card`` is the one a2a-specific flag, threaded in at construction so
        # ``build_manifest`` keeps a uniform signature (like ``kind`` for engine).
        self._card = card

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
            adapter="a2a",
            a2a_card=self._card,
            description=description,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # No host side effects; the backend resolves the card and holds the seat.
        return

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # No host assets and no local runtime; nothing to tear down.
        return

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        lines = [
            f"  adapter:  {manifest.adapter}",
            f"  card:     {manifest.a2a_card}",
        ]
        if manifest.a2a_skills:
            lines.append(f"  skills:   {', '.join(manifest.a2a_skills)}")
        if manifest.allow_from:
            lines.append(f"  allow:    {', '.join(manifest.allow_from)}")
        return lines

    # ── install facet (no host assets; the backend drives the seat) ─────────

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
        return ["  (no host-level install for a2a agents; the backend drives them)"]

    def post_install_banner(
        self,
        *,
        config: MyceliumConfig,
        reinstall: bool,
        profile: str | None,
        container: str | None,
    ) -> None:
        typer.secho("A2A family ready.", fg=typer.colors.GREEN)
        typer.echo("  Register an external A2A agent in a room:")
        typer.secho(
            "    $ mycelium agent create <handle> --adapter a2a --card <url> --room <room>",
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
        # No host binary/asset to probe; the backend owns the seat.
        return {"ok": True, "details": [f"api_url: {info.get('api_url', '')}"]}
