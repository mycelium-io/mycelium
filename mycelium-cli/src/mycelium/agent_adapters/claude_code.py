# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""ClaudeCodeAdapter — the manifest IS the registration.

The cc-daemon discovers ``agents/<handle>`` manifests off the filesystem and
dispatches ``@handle`` mentions to ``claude -p`` spawns. So register/destroy
have no runtime side effects — there's no external service to wire up. This
adapter exists so the command layer has a uniform contract, not because it
does work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium.agent_adapters.base import AddOptions, AgentAdapter
from mycelium.sstp import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude_code"

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
        budget: float,
        allow_from: list[str],
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="claude_code",
            cwd=self._cwd,
            description=description,
            budget_usd_per_month=budget,
            allow_from=allow_from,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # No-op: the cc-daemon picks the manifest up from the filesystem.
        return

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # No external runtime to tear down. `full` is meaningless here — the
        # only artifacts are the manifest (deleted by the command layer) and
        # notes/logs (deliberately preserved).
        return

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
