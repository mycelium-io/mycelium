# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code, as herdr starts it.

Everything that knows Claude Code's own behaviour lives here, so the generic
host and bridge carry none of it (:mod:`kinds` is how they reach it).
"""

from __future__ import annotations

#: Claude Code asks before every shell command it has not been allowed; a member
#: that stops at a prompt on its first ``mycelium await`` never takes its turn,
#: so the one command it needs is allowed for this session only, not in the
#: user's settings.
ARGS = ["--allowedTools", "Bash(mycelium:*)"]


def blocked_hint() -> str:
    """What Claude Code asks for when herdr reads it as blocked.

    herdr can't say which prompt is on screen (none of its rules is specific to
    the first-run one), so this names what it commonly is, never which.
    """
    return (
        "Claude Code asks before it works in a folder it hasn't run in, "
        "and before a command it hasn't been allowed"
    )
