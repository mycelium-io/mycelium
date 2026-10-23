# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mycelium.integrations.agents.base import AgentKind, FirstRun

#: The question Claude Code asks the first time it runs in a folder, in its
#: current words and its older ones, each with the first option, which trusts it.
_TRUST = (
    ("Is this a project you created or one you trust?", "Yes, I trust this folder"),
    ("Do you trust the files in this folder?", "Yes, proceed"),
)
#: What the question adds when the folder's own settings would act without
#: asking (pre-approved tools, extra folders, helper commands). Never answered
#: for the person: that's theirs to read.
_TRUST_GRANTS = (
    "This folder pre-approves",
    "This folder adds",
    "This folder runs commands",
    "These will apply without asking",
    "continue without these permissions",
)


@dataclass(frozen=True)
class Claude(AgentKind):
    def launch_args(self) -> list[str]:
        # It asks before every shell command it hasn't been allowed, and an
        # agent stopped at a prompt on its first `mycelium await` never takes
        # its turn. So the one command it needs is allowed for this session
        # only, never in the person's settings.
        args = ["--allowedTools", "Bash(mycelium:*)"]
        # And it runs in its own auto mode, which decides on each action itself
        # rather than stopping to ask. Never --dangerously-skip-permissions.
        if self.offers("--permission-mode", '"auto"'):
            args += ["--permission-mode", "auto"]
        return args

    def resume_args(self, session: str) -> list[str] | None:
        # The id herdr records for the pane through its Claude integration.
        return ["--resume", session]

    def blocked_hint(self) -> str | None:
        # Nothing says which prompt is on screen (herdr has no rule for the
        # first-run one), so this names what it commonly is, never which.
        return (
            "Claude Code asks before it works in a folder it hasn't run in, "
            "and before a command it hasn't been allowed"
        )

    def first_run(self, screen: str) -> FirstRun | None:
        # The folder was chosen and the start approved on this machine, so its
        # trust question is answered as that person already did: Enter on the
        # first option, which trusts it. Matched as the whole question with its
        # trusting first option; one that names what the folder's own settings
        # would do without asking is left for the person to read.
        lines = [line.strip() for line in screen.splitlines() if line.strip()]
        # A long sentence wraps in a narrow pane, so sentences are looked for
        # across lines; an option is one short line of its own.
        text = re.sub(r"\s+", " ", " ".join(lines))
        for question, yes in _TRUST:
            if question not in text:
                continue
            first = re.compile(rf"^(?:[❯>]\s*)?1\.\s*{re.escape(yes)}$")
            if not any(first.match(line) for line in lines):
                return None
            if any(g in text for g in _TRUST_GRANTS):
                return FirstRun("Claude Code is asking whether to trust this folder's settings")
            return FirstRun(
                "Claude Code is asking whether to trust this folder",
                key="enter",
                done="Trusted the folder for Claude Code",
            )
        return None
