# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What Mycelium knows about each agent CLI herdr starts, one module per kind.

herdr is the switchboard: it knows how to start every kind it lists, and
Mycelium asks it to. What herdr doesn't carry is anything about a CLI past
starting it: the arguments a member needs to run unattended, and how to
start it in a session it can come back to. That knowledge lives here, behind
:class:`AgentKind`, and nowhere else. A kind with no module of its own is the
base class: it starts with no extra arguments and can't be resumed, which is
what every caller handles anyway.

To teach Mycelium another CLI, add a module beside ``claude.py`` and list it
in :data:`KINDS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class FoundSession:
    """A session a CLI left on disk, offered to a person before it's kept."""

    id: str
    path: str
    modified: str


class AgentKind:
    """An agent CLI as herdr names it (``--kind``), with nothing known about it."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    #: What a person calls it.
    @property
    def name(self) -> str:
        return self.kind

    def launch_args(self) -> list[str]:
        """Arguments every member of this kind starts with."""
        return []

    @property
    def resumes(self) -> bool:
        """Whether it can be started in a session and resumed in it later."""
        return False

    def new_session(self) -> tuple[list[str], str] | None:
        """Arguments that start it in a fresh session, and that session's id."""
        return None

    def resume_args(self, session: str) -> list[str]:
        """Arguments that start it again in ``session``."""
        raise NotImplementedError(f"{self.kind} can't be resumed")

    def valid_session(self, value: object) -> str | None:
        """``value`` when it is a session id this CLI could have made, else ``None``.

        A session id ends up as an argument to the CLI, so anything that isn't
        one (a value shaped like a flag, say) is never kept or passed on.
        """
        return None

    def find_session(self, folder: Path) -> FoundSession | None:
        """The newest session this CLI started in ``folder``, if it keeps them where we can look."""
        return None


def _kinds() -> dict[str, AgentKind]:
    from mycelium.integrations.herdr.agents.claude import Claude

    return {k.kind: k for k in (Claude(),)}


#: Every kind Mycelium knows something about, by herdr's name for it.
KINDS: dict[str, AgentKind] = _kinds()


def agent_kind(kind: str | None) -> AgentKind:
    """What Mycelium knows about ``kind``; the base class for one it knows nothing of."""
    return KINDS.get(kind or "") or AgentKind(kind or "")
