# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The floor: who may write into a thread right now.

A thread separates attention, not access — everyone who may write in the room
may write in its threads. Two things narrow that, and both are held by backend
code rather than chosen by a writer. A frozen negotiation admits only the roster
it froze on (:class:`~app.services.l9_slim.EpisodeLifecycle`). A **floor**
admits only the handles its holder has given it to, and it is how a protocol
running inside a task says whose turn it is.

The floor is enforced at the hub's write routes — the one gate ``/messages``
and ``/reply`` both pass (:func:`app.services.tasks.thread_write_refusal`) — so
a write it refuses never reaches the transcript, and since the transcript is
the only delivery path, it wakes nobody. ``await`` needs no change to honor it.

A floor is process-local, like an open negotiation: its holder is a run of
backend code, and a floor dies with the process rather than outliving the run
that would have released it. The room itself (the ``live`` episode) never holds
one: the room stays open, and a floor narrows exactly one thread.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.agent_registry import norm_handle


def _norm(handle: str) -> str:
    """A handle as the floor compares it: bare, so a session of ``@alice``
    (``alice#a8f3``) is ``@alice`` — the floor is given to a member, not to one
    of its sessions."""
    return norm_handle(handle.partition("#")[0]) or ""


@dataclass(frozen=True)
class Floor:
    """One thread's floor: who holds it, and who it has been given to.

    ``holder`` is the handle that set the floor and may always write — the
    engine running a protocol in the thread. ``speakers`` are the handles it has
    given the floor to for the current step; empty means the holder alone.
    """

    episode: str
    holder: str
    speakers: frozenset[str] = frozenset()

    def admits(self, handle: str) -> bool:
        """Whether ``handle`` may write into the thread right now."""
        h = _norm(handle)
        return bool(h) and (h == _norm(self.holder) or h in {_norm(s) for s in self.speakers})

    def describe(self) -> str:
        """The floor as a refusal reads it: who holds it, and who may speak."""
        if self.speakers:
            names = ", ".join(f"@{s}" for s in sorted(self.speakers))
            return f"@{self.holder} holds the floor; {names} may speak"
        return f"@{self.holder} holds the floor; no one else may speak right now"
