# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Codex."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mycelium.integrations.agents.base import AgentKind


@dataclass(frozen=True)
class Codex(AgentKind):
    def launch_args(self) -> list[str]:
        # Codex runs commands in a sandbox with no network that can write only
        # in the folder it started in, so `mycelium` can neither reach the hub
        # nor write its own settings, and every call ends at an approval
        # prompt. An agent stopped at one on its first `mycelium await` never
        # takes its turn. So for this session only, never in the person's
        # settings, the sandbox gets the network and the one folder `mycelium`
        # writes to. Everything else stays as sandboxed as it was.
        return [
            "-c",
            "sandbox_workspace_write.network_access=true",
            "--add-dir",
            str(Path.home() / ".mycelium"),
        ]

    def blocked_hint(self) -> str | None:
        # Like Claude's: what it commonly waits for, never which prompt is up.
        return (
            "Codex asks before it works in a folder it hasn't run in, "
            "and before a command its sandbox doesn't allow"
        )
