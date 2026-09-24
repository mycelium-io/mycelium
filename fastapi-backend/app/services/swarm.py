# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A swarm's shape: the room it runs in, the team, and the kickoff that starts it.

A swarm is a task a team of workers takes on together. Setting one up is the
ordinary room, engine, task and message writes, in order (``routes/swarms``);
this holds the naming those writes share with ``mycelium swarm``, which does
the same setup from the CLI for a team it starts in herdr.
"""

from __future__ import annotations

import re

#: How many members a swarm starts with, and the most it may have.
DEFAULT_SIZE = 3
MAX_SIZE = 8
#: The conductor's handle in a swarm room, and the flow it runs.
CONDUCTOR = "conductor"
FLOW = "swarm"

_SLUG = re.compile(r"[^a-z0-9]+")
#: Words a room name reads fine without.
_FILLER = frozenset({"a", "an", "the", "for", "to", "of", "and", "in", "on", "with", "our"})


def room_slug(task: str, limit: int = 40) -> str:
    """A room name from a task: its words, lowercase, joined by dashes.

    Filler words go first, and the name stops at the last whole word that fits,
    so a long task reads as a name rather than a string cut mid-word. Mirrors
    ``mycelium.commands.swarm.room_slug``.
    """
    words = [w for w in _SLUG.split(task.lower()) if w]
    kept = [w for w in words if w not in _FILLER] or words
    slug = ""
    for word in kept:
        candidate = f"{slug}-{word}" if slug else word
        if len(candidate) > limit:
            break
        slug = candidate
    return slug or (kept[0][:limit] if kept else "swarm")


def team_handles(size: int) -> list[str]:
    """The members of a swarm of ``size``: ``agent-1`` onward."""
    return [f"agent-{i}" for i in range(1, size + 1)]


def kickoff_text(team: list[str], task: str) -> str:
    """The message that summons the conductor to run the kickoff over the team."""
    names = " ".join(f"@{h}" for h in team)
    return f"@{CONDUCTOR} {FLOW} {names}: {task}"
