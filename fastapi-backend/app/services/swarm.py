# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A swarm's shape: the team, and the kickoff that starts it.

A swarm is a task in a room that a team takes on together. Setting one up is
the ordinary engine, task and message writes, in order (``routes/swarms``);
this holds the naming those writes share with ``mycelium swarm``, which does
the same setup from the CLI for a team it starts in herdr.
"""

from __future__ import annotations

#: How many members a swarm starts with, and the most it may have.
DEFAULT_SIZE = 3
MAX_SIZE = 8
#: The conductor's handle in a swarm's room, and the flow it runs.
CONDUCTOR = "conductor"
FLOW = "swarm"


def team_handles(size: int) -> list[str]:
    """The members of a swarm of ``size``: ``agent-1`` onward."""
    return [f"agent-{i}" for i in range(1, size + 1)]


def kickoff_text(team: list[str], task: str) -> str:
    """The message that summons the conductor to run the kickoff over the team."""
    names = " ".join(f"@{h}" for h in team)
    return f"@{CONDUCTOR} {FLOW} {names}: {task}"
