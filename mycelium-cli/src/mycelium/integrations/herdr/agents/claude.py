# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code, as herdr's ``claude`` kind."""

from __future__ import annotations

from mycelium.integrations.herdr.agents import AgentKind


class Claude(AgentKind):
    def __init__(self) -> None:
        super().__init__("claude")

    def launch_args(self) -> list[str]:
        # It asks before every shell command it hasn't been allowed, and a
        # member stopped at a prompt on its first `mycelium await` never takes
        # its turn. So the one command it needs is allowed for this session
        # only, never in the person's settings.
        return ["--allowedTools", "Bash(mycelium:*)"]
