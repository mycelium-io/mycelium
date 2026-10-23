# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mycelium.integrations.agents.base import AgentKind, FirstRun


@dataclass(frozen=True)
class _Trust:
    """One wording of the question Claude Code asks the first time it runs in a folder."""

    #: The question's first line.
    start: str
    #: Every sentence it says, as patterns over its text with the wrapping undone.
    prose: tuple[str, ...]
    #: Its options, in the order it lists them.
    options: tuple[str, ...]
    #: The one that trusts the folder.
    yes: str


#: The plain question, in Claude Code's current words and its older ones. It is
#: answered only when nothing else is on it: a folder whose own settings would
#: act without asking (pre-approved tools, extra folders, helper commands, or
#: anything a later release adds) shows more, and is left for the person.
_TRUST = (
    # Claude Code 2.x: no numbers, "No, exit" first and picked, so the answer
    # is Down to "Yes", then Enter once it's the one picked.
    _Trust(
        start="Accessing workspace:",
        prose=(
            r"Quick safety check: Is this a project you created or one you trust\? "
            r"\(Like your own code, a well-known open source project, or work from your "
            r"team\)\. If not, take a moment to review what.s in this folder first\.",
            r"[\w ]{0,20}.ll be able to read, edit, and execute files here\.",
            r"Security guide",
        ),
        options=("No, exit", "Yes, I trust this folder"),
        yes="Yes, I trust this folder",
    ),
    _Trust(
        start="Do you trust the files in this folder?",
        prose=(
            r"Claude Code may read, write, or execute files contained in this directory\. "
            r"This can pose security risks, so only use files from trusted sources\.",
            r"Learn more",
        ),
        options=("Yes, proceed", "No, exit"),
        yes="Yes, proceed",
    ),
)
#: An option line: the pointer on the one picked, a number in older versions.
_OPTION = re.compile(r"^(❯\s*)?(?:\d\.\s*)?(.+)$")
#: A line of key hints under the options ("Enter to confirm · Esc to cancel"):
#: nothing but "<key> to <a word or two>" hints, so no warning passes as one.
_HINT = r"(?:Enter|Esc|Tab|↑/↓|↑↓)\s+to\s+[a-z]+(?:\s[a-z]+)?"
_KEYS = re.compile(rf"^{_HINT}(?:\s*·\s*{_HINT})*$")
_BORDER = "│╭╮╰╯─ "


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
        # The folder was chosen and the start approved on this machine, so the
        # plain trust question is answered as that person already did: its
        # trusting option is picked, then confirmed. Anything on it beyond the
        # question leaves it for the person, so a change in its wording costs
        # them an Enter, never a yes they didn't see.
        lines = [line.strip(_BORDER) for line in screen.splitlines()]
        lines = [line for line in lines if line]
        for trust in _TRUST:
            starts = [i for i, line in enumerate(lines) if line == trust.start]
            if not starts:
                continue
            held = FirstRun("Claude Code is asking whether to trust this folder")
            # From the question's first line on; what's above it is the shell
            # it was started from.
            body = lines[starts[-1] + 1 :]
            # The folder it names.
            if body and body[0].startswith(("/", "~")):
                body = body[1:]
            options: list[str] = []
            picked: list[str] = []
            prose: list[str] = []
            for line in body:
                option = _OPTION.match(line)
                label = option.group(2).strip() if option else line
                pointer = bool(option and option.group(1))
                if label in trust.options or pointer:
                    options.append(label)
                    if pointer:
                        picked.append(label)
                elif not _KEYS.match(line):
                    prose.append(line)
            if tuple(options) != trust.options or len(picked) != 1:
                return held
            # A long sentence wraps in a narrow pane; each known one is taken
            # out once, and anything left over is something it doesn't know.
            text = re.sub(r"\s+", " ", " ".join(prose)).replace("’", "'")
            for sentence in trust.prose:
                text = re.sub(sentence, "", text, count=1)
            if text.strip():
                return held
            if picked[0] == trust.yes:
                return FirstRun(held.what, key="enter", done="Trusted the folder for Claude Code")
            # Move to it; it's confirmed once it reads as the one picked.
            up = options.index(trust.yes) < options.index(picked[0])
            return FirstRun(held.what, key="up" if up else "down")
        return None
