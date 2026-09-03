# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Put a status provider's answer on the row that mentioned it.

The hub resolves every external reference a room's text names and returns them
keyed by the board row ids that mention them, so this does no parsing: it looks
up a row's id and lands the answer under ``upstream``.

**The state is the field; the rest are companions.** ``upstream`` carries the
state alone — a closed vocabulary the board can group, filter and color by,
the same way it treats ``status`` and ``ci``. The provider's own wording, its
link and the answer's age ride alongside in their own fields, the same way a
row already carries ``pr``, ``ci`` and ``branch``.

**A row that names two things shows the worse one.** A task blocked on one
pull request and green on another reads as blocked; ``upstream_count`` says
there was more than one.

**Not knowing yet is ``upstream_pending``, not ``unknown``.** The hub answers a
read from cache and refreshes behind it, so the first read of a room has
references but no answers yet; ``unknown`` is reserved for a state a provider
reports when it meets something it cannot place. A pending row carries no
``upstream`` at all, so grouping by the field never collects a bucket of rows
that were merely early.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mycelium.board.model import LiveItem

#: Worst-first ranking: a row with several references takes the first state in
#: this order that any of them is in.
UPSTREAM_STATES = ["failed", "blocked", "pending", "ok", "done", "unknown"]

FIELD = "upstream"


def _rank(state: str | None) -> int:
    try:
        return UPSTREAM_STATES.index(state or "unknown")
    except ValueError:
        return len(UPSTREAM_STATES)


def _age(seconds: float | None) -> str | None:
    """A human reading of how old an answer is, in the same shape a row's other
    ages take. An answer with no age was never fetched, and says nothing."""
    if seconds is None:
        return None
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"


def attach_upstream(items: list[LiveItem], status: dict[str, Any] | None) -> list[LiveItem]:
    """Land each row's upstream answer on it, in place, and return the rows.

    A row nothing was found for is left exactly as it was: no field, rather than
    an empty one, so a view can tell "nothing upstream" from "upstream unknown".
    """
    if not status:
        return items

    by_ref = {entry.get("ref"): entry for entry in status.get("refs", []) if entry.get("ref")}
    rows = status.get("rows") or {}

    refreshing = bool(status.get("refreshing"))

    for item in items:
        answers = [by_ref[ref] for ref in rows.get(item.id, []) if ref in by_ref]
        if not answers:
            continue
        # A resolved answer outranks one still coming, so a row with two
        # references shows what is known rather than waiting on the slowest.
        answers.sort(key=lambda a: (a.get("state") is None, _rank(a.get("state"))))
        worst = answers[0]

        if len(answers) > 1:
            item.fields["upstream_count"] = len(answers)
        item.fields["upstream_freshness"] = worst.get("freshness")

        # Nothing has come back for this row yet. Say so, rather than showing a
        # state nobody reported.
        if worst.get("state") is None:
            item.fields["upstream_pending"] = worst.get("freshness") == "missing" or refreshing
            item.fields["upstream_label"] = worst.get("error")
            continue

        item.fields[FIELD] = worst["state"]
        # An errored answer has no label of its own, so the reason stands in:
        # "not visible to this token" is the honest wording for that row.
        item.fields["upstream_label"] = worst.get("label") or worst.get("error")
        item.fields["upstream_url"] = worst.get("url")
        item.fields["upstream_age"] = _age(worst.get("age_seconds"))
    return items
