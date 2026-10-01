# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What Mycelium adds when it starts an agent CLI, one module per kind.

herdr is the switchboard: it starts every kind it lists, and with its
integration installed it keeps track of each agent's session and restarts it
there after its own server restarts. Mycelium knows nothing about a CLI's
sessions. What it does add is anything a member needs to run unattended,
which lives here, behind :class:`AgentKind`, and nowhere else. A kind with no
module of its own is the base class and starts with no extra arguments.
"""

from __future__ import annotations


class AgentKind:
    """An agent CLI as herdr names it (``--kind``), with nothing added."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def launch_args(self) -> list[str]:
        """Arguments every member of this kind starts with."""
        return []


def _kinds() -> dict[str, AgentKind]:
    from mycelium.integrations.herdr.agents.claude import Claude

    return {k.kind: k for k in (Claude(),)}


#: Every kind Mycelium adds something to, by herdr's name for it.
KINDS: dict[str, AgentKind] = _kinds()


def agent_kind(kind: str | None) -> AgentKind:
    """What Mycelium adds for ``kind``; the base class for one it adds nothing to."""
    return KINDS.get(kind or "") or AgentKind(kind or "")
