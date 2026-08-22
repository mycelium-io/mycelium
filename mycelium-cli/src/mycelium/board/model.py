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
STATUSES = [
    "open",
    "claimed",
    "in_progress",
    "in_review",
    "blocked",
    "resolved",
    "dismissed",
]
KINDS = ["decision", "blocked", "review", "action", "concern", "signal"]
PRIORITIES = ["urgent", "high", "normal", "low"]
LENSES = ["needs_you", "in_flight", "resolved"]
VERBS = ["claim", "resolve", "block", "unblock", "promote", "dismiss"]

#: The lens is derived from status, never stored, so a row can't drift out of
#: sync with the board it belongs on.
LENS_OF_STATUS = {
    "open": "needs_you",
    "blocked": "needs_you",
    "claimed": "in_flight",
    "in_progress": "in_flight",
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

    @property
    def lens(self) -> str:
        return lens_of(self.status)

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
