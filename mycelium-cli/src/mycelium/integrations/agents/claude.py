# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code."""

from __future__ import annotations

from dataclasses import dataclass

from mycelium.integrations.agents.base import AgentKind


@dataclass(frozen=True)
class Claude(AgentKind):
    def launch_args(self) -> list[str]:
        # It asks before every shell command it hasn't been allowed, and an
        # agent stopped at a prompt on its first `mycelium await` never takes
        # its turn. So the one command it needs is allowed for this session
        # only, never in the person's settings.
        return ["--allowedTools", "Bash(mycelium:*)"]

    def blocked_hint(self) -> str | None:
        # Nothing says which prompt is on screen (herdr has no rule for the
        # first-run one), so this names what it commonly is, never which.
        return (
            "Claude Code asks before it works in a folder it hasn't run in, "
            "and before a command it hasn't been allowed"
        )
