# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""ClaudeCode dispatch facet: the manifest IS the registration.

A ``claude_code`` agent is a **resident** runtime: a Claude Code session (kept
woken with ``mycelium await --loop``) that participates via ``await``/``respond``.
Mycelium names the agent (the ``agents/<handle>`` manifest); it does not run
the process. So register/destroy have no runtime side effects; this exists so
the command layer has a uniform contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium.integrations.base import AddOptions, Integration
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class ClaudeCodeIntegration(Integration):
    name = "claude_code"
    lifecycle = "resident"

    def __init__(self, *, cwd: str | None = None) -> None:
        # cwd is collected by the command layer (it's a claude_code-only flag)
        # and threaded in at construction so build_manifest stays uniform.
        self._cwd = cwd

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
            adapter="claude_code",
            cwd=self._cwd,
            description=description,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # No runtime side effects: a claude_code agent is a resident session the
        # user runs (via `mycelium await --loop`), not a process mycelium spawns.
        # The manifest (persisted by the command layer) is the whole registration.
        return

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # No external runtime to tear down. `full` is meaningless here; the only
        # artifacts are the manifest (deleted by the command layer) and notes/logs
        # (deliberately preserved).
        return

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


#: Back-compat alias for the historical class name.
ClaudeCodeAdapter = ClaudeCodeIntegration
