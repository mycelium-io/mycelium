# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The board's row primitive and the vocabulary it is written in.

A row is a stable identity plus a bag of frontmatter ``fields``.  Every view —
the steer-attention_filter, the kanban, the typed table — is a projection over that bag, so
a coordination surface and a typed view over a namespace are one mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Frozen in contracts/board-vocabulary.json; the GUI carries the same lists.
#: The stage a row is at, and only that. Who holds it is ``assignment`` (a lease
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
ATTENTION_FILTERS = ["needs_you", "in_flight", "resolved"]
ROW_ACTIONS = ["claim", "release", "resolve", "block", "unblock", "promote", "dismiss"]

#: The attention filter is derived from status, never stored, so a row can't drift out of
#: sync with the board it belongs on. This is the half for rows nobody holds;
#: a row with a lease is lensed by its assignment instead (``assignment.attention_of_item``).
ATTENTION_OF_STATUS = {
    "open": "needs_you",
    "in_review": "in_flight",
    "resolved": "resolved",
    "dismissed": "resolved",
}

LIVE_NAMESPACES = ["decisions", "status", "work", "failed"]


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


def attention_of_status(status: str) -> str:
    return ATTENTION_OF_STATUS.get(status, "needs_you")


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
