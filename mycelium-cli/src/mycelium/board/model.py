# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The board's row primitive and the vocabulary it is written in.

A row is a stable identity plus a bag of frontmatter ``fields``.  Every view —
the steer-lens, the kanban, the typed table — is a projection over that bag, so
a coordination surface and a typed view over a namespace are one mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Frozen in contracts/board-vocabulary.json; the GUI carries the same lists.
#: The stage a row is at, and only that. Who holds it is ``custody`` (a lease
#: that drains), and whether it is blocked is derived from ``blocked_by`` — both
#: used to be spelled here, which is how one field ended up doing three jobs.
STATUSES = [
    "open",
    "in_review",
    "resolved",
    "dismissed",
]
KINDS = ["decision", "blocked", "review", "action", "concern", "signal"]
PRIORITIES = ["urgent", "high", "normal", "low"]
LENSES = ["needs_you", "in_flight", "resolved"]
#: What a verb does to the row it names. A **mutation** verb changes the row —
#: its custody through a lease, everything else as frontmatter. A **chat** verb
#: changes nothing about the row and speaks in the thread the row *is*: the
#: room's own chat verbs with a row id in front of them. Kept as two lists
#: rather than one because a reader has to be able to tell, from the word alone,
#: whether a typo just wrote a field or posted a message.
VERBS = ["claim", "release", "resolve", "block", "unblock", "promote", "dismiss", "new"]
CHAT_VERBS = ["send", "messages", "coordinate"]

#: The lens is derived from status, never stored, so a row can't drift out of
#: sync with the board it belongs on. This is the half for rows nobody holds;
#: a row with a lease is lensed by its custody instead (``custody.lens_of_item``).
LENS_OF_STATUS = {
    "open": "needs_you",
    "in_review": "in_flight",
    "resolved": "resolved",
    "dismissed": "resolved",
}

LIVE_NAMESPACES = ["decisions", "status", "work", "failed"]

#: The store-owned frontmatter key binding a row to its thread. Minted by the
#: backend and carried across writes, so a row's thread is stable for its life.
EPISODE_FIELD = "episode"

#: What a row says about the thread inside it. Deliberately its own names: a
#: unit's ``status`` and ``custody`` are the unit's, so a negotiation that
#: converges inside a row must not resolve the row or take it off its holder.
THREAD_FIELDS = ["episode", "thread", "thread_state", "participants", "rounds"]

#: How the thread inside a unit reads. ``open`` while it is still running;
#: the rest are the commit subkinds a negotiation closes on.
THREAD_STATES = ["open", "converged", "resolved", "rejected", "committed"]

#: The row's own axes, which folding a thread onto it must never write. This is
#: the container-outlives-the-negotiation rule as a list.
UNIT_FIELDS = ["status", "custody", "owner", "kind", "priority"]

#: Why a projected row has no thread to speak into, keyed by what produced it.
#: A chat verb refuses in these terms rather than falling back to the room: a
#: message that quietly went somewhere other than where it was addressed is
#: worse than one that did not go.
THREAD_REFUSALS = {
    "agent": "presence is a lease the runtime renews, not a conversation to join",
    "memory": "a thread belongs to a unit of work; this row is in another namespace",
}


@dataclass(frozen=True)
class ItemSource:
    """What produced a row, in the room's own terms."""

    kind: str
    label: str


@dataclass
class LiveItem:
    id: str
    title: str
    source: ItemSource
    fields: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        value = self.fields.get(name)
        return None if value == "" else value

    def text(self, name: str) -> str | None:
        value = self.get(name)
        return value.strip() if isinstance(value, str) and value.strip() else None

    def strings(self, name: str) -> list[str]:
        value = self.get(name)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, str)]
        return [value] if isinstance(value, str) else []

    @property
    def status(self) -> str:
        value = self.text("status")
        return value if value in STATUSES else "open"

    @property
    def kind(self) -> str:
        value = self.text("kind")
        return value if value in KINDS else "action"

    @property
    def priority(self) -> str:
        value = self.text("priority")
        return value if value in PRIORITIES else "normal"

    @property
    def owner(self) -> str | None:
        value = self.text("owner")
        return value.lstrip("@") if value else None

    def age_minutes(self, now: datetime) -> int | None:
        raw = self.text("updated") or self.text("created")
        if not raw:
            return None
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return max(0, int((now - stamp).total_seconds() // 60))


def lens_of(status: str) -> str:
    return LENS_OF_STATUS.get(status, "needs_you")


def priority_rank(item: LiveItem) -> int:
    return PRIORITIES.index(item.priority)


def format_age(minutes: int | None) -> str:
    if minutes is None:
        return "-"
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"
