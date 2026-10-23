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
        settings = [
            "-c",
            "sandbox_workspace_write.network_access=true",
            "--add-dir",
            str(state),
        ]
        # The sandbox those settings belong to is chosen here too, never left
        # to the person's config or whether the folder is trusted: a folder
        # Codex hasn't been asked about starts read-only, where Codex refuses
        # the extra folder and exits. Still a sandbox, never `danger-full-access`
        # and never the bypass.
        if self.offers("--approve-for-me"):
            # Codex 0.147 and later: workspace-write with its approvals going to
            # its own automatic review instead of stopping to ask. The flag sets
            # the sandbox itself, and Codex refuses it beside `--sandbox` or
            # `--ask-for-approval`, so neither is passed with it.
            return ["--approve-for-me", *settings]
        # An older Codex: the same sandbox, asking the person only for what it
        # doesn't allow. The config keys work on one too old for the flags.
        if self.offers("--sandbox"):
            mode = ["--sandbox", "workspace-write", "--ask-for-approval", "on-request"]
        else:
            mode = ["-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="on-request"']
        return [*mode, *settings]

    def blocked_hint(self) -> str | None:
        # Like Claude's: what it commonly waits for, never which prompt is up.
        return (
            "Codex asks before it works in a folder it hasn't run in, "
            "and before a command its sandbox doesn't allow"
        )

    def not_ready(self) -> str | None:
        # A Codex that isn't signed in opens on its sign-in and welcome screens,
        # which herdr reads as idle and ready: the introduction and the first
        # wake would be typed into a screen that only takes Enter. Codex's own
        # `login status` says which (0 signed in, 1 not), so ask before starting.
        # Anything else it says (an old Codex without the command, a config it
        # can't read) is left for the start itself to report.
        done = self.run("login", "status")
        if done is None or done.returncode == 0:
            return None
        if "not logged in" not in f"{done.stdout}\n{done.stderr}".lower():
            return None
        return (
            "Codex isn't signed in here yet. Run `codex` once in a terminal on this "
            "machine, sign in, and press Enter past its welcome screen. Then try again."
        )
