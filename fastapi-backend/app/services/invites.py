# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Consent-gated invites — the human-in-the-room membership flow (Step 6, bible §12).

An ``@``-mention of an agent **already on the room channel** is a *wake* (handled
on the fabric: the human's ``exchange`` names it as an L9 recipient and its
connector wakes). An ``@``-mention of an agent **not on the channel** is a
*membership change* — and a membership change is a consent decision, not a
side effect. So instead of inviting straight away, the backend records a
:class:`PendingInvite` and surfaces an accept/decline prompt ("someone's agent
wants to reach yours — accept?"). The moderator only invites + spawns on accept.

This registry is the pure, node-free state of that flow. The SLIM side (actually
inviting on accept, and the mid-episode queue) lives on
:class:`~app.services.room_channels.RoomChannelManager`, which drives this.

States:

- ``pending``   — consent prompt raised, awaiting a human decision.
- ``queued``    — accepted, but an episode was live, so the membership change is
                  deferred until the episode closes (L9's stable-membership rule,
                  bible §12: a mid-episode join would abort the episode).
- ``accepted``  — accepted and applied (the moderator invited the agent).
- ``declined``  — declined (or dropped); never joins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

PENDING = "pending"
QUEUED = "queued"
ACCEPTED = "accepted"
DECLINED = "declined"

# Statuses that still represent an open (not-yet-resolved) consent request.
OPEN_STATES = frozenset({PENDING, QUEUED})


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class PendingInvite:
    """One consent-gated invite of ``agent`` into ``room``."""

    id: str
    room: str
    agent: str
    requested_by: str
    trigger_text: str = ""
    status: str = PENDING
    created_at: str = field(default_factory=_now)

    def to_json(self) -> dict[str, str]:
        return {
            "id": self.id,
            "room": self.room,
            "agent": self.agent,
            "requested_by": self.requested_by,
            "trigger_text": self.trigger_text,
            "status": self.status,
            "created_at": self.created_at,
        }


class PendingInviteRegistry:
    """In-memory registry of consent-gated invites, keyed by invite id.

    :meth:`request` is idempotent per open ``(room, agent)``: a second mention of
    the same absent agent while a consent prompt is still open returns the same
    invite rather than stacking duplicate prompts.
    """

    def __init__(self) -> None:
        self._invites: dict[str, PendingInvite] = {}

    def request(
        self, room: str, agent: str, *, requested_by: str, trigger_text: str = ""
    ) -> PendingInvite:
        """Record (or return the open) consent request for ``agent`` in ``room``."""
        existing = self._open_for(room, agent)
        if existing is not None:
            return existing
        invite = PendingInvite(
            id=str(uuid.uuid4()),
            room=room,
            agent=agent,
            requested_by=requested_by,
            trigger_text=trigger_text,
        )
        self._invites[invite.id] = invite
        return invite

    def get(self, invite_id: str) -> PendingInvite | None:
        return self._invites.get(invite_id)

    def open_for_room(self, room: str) -> list[PendingInvite]:
        """Every still-open (pending or queued) invite in ``room``."""
        return [
            inv for inv in self._invites.values() if inv.room == room and inv.status in OPEN_STATES
        ]

    def queued_for_room(self, room: str) -> list[PendingInvite]:
        """Accepted-but-deferred invites in ``room`` (mid-episode queue)."""
        return [inv for inv in self._invites.values() if inv.room == room and inv.status == QUEUED]

    def mark(self, invite_id: str, status: str) -> PendingInvite | None:
        invite = self._invites.get(invite_id)
        if invite is None:
            return None
        invite.status = status
        return invite

    def _open_for(self, room: str, agent: str) -> PendingInvite | None:
        for inv in self._invites.values():
            if inv.room == room and inv.agent == agent and inv.status in OPEN_STATES:
                return inv
        return None
