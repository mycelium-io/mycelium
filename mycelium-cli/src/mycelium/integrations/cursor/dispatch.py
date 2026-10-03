# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor dispatch facet: manifest IS the registration (same shape as claude_code).

A ``cursor`` agent is a **resident** runtime: a Cursor session (kept woken with
``mycelium await --loop``) that participates via ``await``/``respond``. Registration
drops the workspace-local Cursor rule + AGENTS.md section so the session knows how
to coordinate; mycelium does not run the process. (Untested end-to-end; kept as the
resident sibling of claude_code.)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mycelium.integrations.base import AddOptions, Integration
from mycelium.integrations.cursor.install import (
    install_workspace_assets,
    uninstall_workspace_assets,
)
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class CursorIntegration(Integration):
    name = "cursor"
    lifecycle = "resident"

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
        allow_from: list[str],
        owner: str | None = None,
        team: str | None = None,
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="cursor",
            cwd=self._cwd,
            description=description,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # Drop the workspace-local Cursor rule + AGENTS.md section so a resident
        # Cursor session knows how to coordinate. ``install_workspace_assets``
        # raises ``NotADirectoryError`` when ``manifest.cwd`` doesn't exist; the
        # command layer surfaces that as a clean validation error. No runtime is
        # started; the user runs the session (via ``mycelium await --loop``).
        if manifest.cwd:
            install_workspace_assets(Path(manifest.cwd), verbose=False)

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # ``full`` requests destructive teardown of *this agent's runtime*
        # (for cursor that means removing the workspace assets we dropped).
        # Without ``full``, we leave them in place so a re-add picks up where
        # we left off and the user's project-rules history isn't disturbed.
        # The agent's manifest and notes/logs are owned by the command layer
        # and never touched here.
        if full and manifest.cwd:
            cwd_path = Path(manifest.cwd)
            if cwd_path.exists():
                uninstall_workspace_assets(cwd_path, verbose=False)

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        lines: list[str] = [
            f"  adapter: {manifest.adapter}",
        ]
        if manifest.cwd:
            lines.append(f"  cwd:     {manifest.cwd}")
        if manifest.allow_from:
            lines.append(f"  allow:   {', '.join(manifest.allow_from)}")
        lines.append(
            "\n[dim]Seed the agent's brain (optional):[/dim]\n"
            f'  mycelium memory set {manifest.notes_key} "..." --room {room}\n'
            "[dim]Keep the agent woken so it can answer:[/dim]\n"
            f'  mycelium await --loop --room {room} --handle {manifest.handle} --exec "..."\n'
            "[dim]Or address it (it picks up on its next await):[/dim]\n"
            f'  mycelium agent invoke {manifest.handle} "..."'
        )
        return lines

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        # ``full`` removes the workspace assets; confirm in the command
        # layer because users may have committed AGENTS.md and don't expect
        # ``agent rm --full`` to mutate their git working tree.
        return bool(full and manifest.cwd)


#: Back-compat alias for the historical class-name convention.
CursorAdapter = CursorIntegration
