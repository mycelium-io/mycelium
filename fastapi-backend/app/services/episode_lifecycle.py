# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""One episode's lifecycle inside a room: whether a negotiation holds its
parties fixed, and the record that closes one a party left."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services import message_format
from app.services.message_models import Kind

if TYPE_CHECKING:
    from app.services.message_models import MyceliumMessage


@dataclass
class EpisodeLifecycle:
    """Tracks one episode within a room.

    **Freezing membership is a negotiation's policy, not an episode's.** An
    offer/counter exchange scored across a changing set of parties means
    nothing, so a negotiation freezes its own parties (:attr:`members`: the
    handles it was asked to broker between, not everyone present) and
    **aborts** only when one of them is removed from the room. Presence coming
    and going is not that: in a busy room someone's lease starts or lapses
    every minute, and an agent between turns isn't connected at all.

    A task is an episode too, and nothing about it wants that rule: it is a
    container that outlives what happens inside it, so someone joining the
    room must not end the thread a board row's history lives in. Such an
    episode opens with ``negotiation=False``, and :attr:`frozen`, not
    :attr:`active`, is what callers gate the freeze on.
    """

    episode: str | None = None
    members: frozenset[str] = field(default_factory=frozenset)
    active: bool = False
    negotiation: bool = True

    @property
    def frozen(self) -> bool:
        """Whether membership is frozen right now: an active *negotiation*."""
        return self.active and self.negotiation

    def open(
        self, episode: str, members: set[str] | frozenset[str], *, negotiation: bool = True
    ) -> None:
        """Begin an episode; a negotiation's ``members`` are its parties.

        ``negotiation=False`` opens a container (a task's thread) that a
        later join or leave leaves running.
        """
        self.episode = episode
        self.members = frozenset(members)
        self.active = True
        self.negotiation = negotiation

    def on_member_removed(self, handle: str) -> bool:
        """Record ``handle`` leaving the room; True if that aborts a negotiation,
        which it does only when ``handle`` is one of the negotiation's parties."""
        if self.frozen and handle in self.members:
            self.active = False
            return True
        return False

    def close(self) -> None:
        """Close the episode normally."""
        self.active = False
        self.episode = None
        self.negotiation = True


def build_episode_abort_envelope(
    episode: str,
    *,
    recipients: list[str],
    topic: str | None = None,
    reason: str = "membership_change",
) -> MyceliumMessage:
    """The ``commit:rejected`` envelope that closes an aborted episode."""
    return message_format.build_envelope(
        kind=Kind.commit,
        subkind="rejected",
        episode=episode,
        recipients=recipients,
        topic=topic,
        payload_type="consensus",
        payload_data={"aborted": True, "reason": reason},
    )
