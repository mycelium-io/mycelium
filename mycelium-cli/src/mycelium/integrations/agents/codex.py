# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Codex."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from mycelium.integrations.agents.base import AgentKind


@dataclass(frozen=True)
class Codex(AgentKind):
    def launch_args(self) -> list[str]:
        # Codex runs commands in a sandbox with no network that can write only
        # in the folder it started in, so `mycelium` can't reach the hub, and
        # every call ends at an approval prompt. An agent stopped at one on its
        # first `mycelium await` never takes its turn. So for this session
        # only, never in the person's settings, the sandbox gets the network
        # and the one folder the CLI writes to from inside an agent (its
        # pending confirmations and minted tokens). Never the rest of
        # ~/.mycelium: the config, the herdr registry and the runner's approval
        # files are there, and an agent that could write those could approve
        # its own launches or point the CLI at another hub.
        from mycelium.config import MyceliumConfig

        state = MyceliumConfig.get_agent_state_dir()
        # Codex wants the folder to exist; if it can't be made, mycelium still
        # runs, only without keeping what it can't write.
        with contextlib.suppress(OSError):
            state.mkdir(parents=True, exist_ok=True)
        args = ["-c", "sandbox_workspace_write.network_access=true", "--add-dir", str(state)]
        # And its approvals go to its own automatic review instead of stopping
        # to ask, inside that sandbox. Never the bypass that drops the sandbox.
        if self.offers("--approve-for-me"):
            args.append("--approve-for-me")
        return args

    def session_note(self) -> str | None:
        # The sandbox is opened per session, where nobody sees it: say so where it's picked.
        if self.offers("--approve-for-me"):
            return "Codex runs in its auto mode, and can reach the hub and its own Mycelium state"
        return "Codex can reach the hub and its own Mycelium state"

    def blocked_hint(self) -> str | None:
        # Like Claude's: what it commonly waits for, never which prompt is up.
        return (
            "Codex asks before it works in a folder it hasn't run in, "
            "and before a command its sandbox doesn't allow"
        )
