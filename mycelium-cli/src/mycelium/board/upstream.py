# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Put a status provider's answer on the row that mentioned it.

The hub resolves every external reference a room's text names and returns them
keyed by the board row ids that mention them, so this does no parsing: it looks
up a row's id and lands the answer under ``upstream``.

**The state is the field; the rest are companions.** ``upstream`` carries the
state alone (a closed vocabulary the board can group, filter and colour by, the
same way it treats ``status`` and ``ci``) rather than an object, which inference
would type as free text and no view could group. The provider's own wording, its
link and the answer's age ride alongside in their own fields, which is how a row
already carries ``pr``, ``ci`` and ``branch``.

**A row that names two things shows the worse one.** Rows are how a board says
what needs you, so a task blocked on one pull request and green on another reads
as blocked; ``upstream_count`` says there was more than one, so the summary never
quietly stands in for the whole.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mycelium.board.model import LiveItem

#: Worst first. A row with several references takes the first state in this order
#: that any of them is in, because a board exists to surface the thing that needs
#: a person, not to average.
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

    for item in items:
        answers = [by_ref[ref] for ref in rows.get(item.id, []) if ref in by_ref]
        if not answers:
            continue
        answers.sort(key=lambda a: _rank(a.get("state")))
        worst = answers[0]

        item.fields[FIELD] = worst.get("state") or "unknown"
        # An errored answer has no label of its own, so the reason stands in:
        # "not visible to this token" is the honest wording for that row.
        item.fields["upstream_label"] = worst.get("label") or worst.get("error")
        item.fields["upstream_url"] = worst.get("url")
        item.fields["upstream_age"] = _age(worst.get("age_seconds"))
        if len(answers) > 1:
            item.fields["upstream_count"] = len(answers)
    return items
