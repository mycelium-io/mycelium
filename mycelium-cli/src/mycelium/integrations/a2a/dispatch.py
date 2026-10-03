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
