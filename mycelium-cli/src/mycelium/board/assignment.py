# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Assignment: who holds a row, and for how much longer.

An agent is resident rather than one-shot, and a session can end without
announcing it — a container is reclaimed, a cloud session times out, a job is
canceled. Assignment is a lease rather than a stored fact: a live claim reads
fresh/stale/expired against ``claimed_at`` + a TTL, the same freshness model
the upstream half uses against ``fetched_at``. An abandoned claim drains and
the row returns to the pool.

**Assignment is not a stage.** ``status`` is a stage vocabulary. Assignment is
the axis that says whether anyone is actually on this: ``in_review`` says
nothing about whether a holder is alive, ``held, renewed 30s ago`` does.

**Two states are derived and never stored.** ``unclaimed`` is the absence of a
holder; ``expired`` is a lease nobody renewed. Neither is written to disk —
both are read off the clock at query time.

``renewed`` is not a state: it is the event that keeps ``held`` fresh, and does
not appear in the enum.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mycelium.board.model import LiveItem

# Frozen in contracts/board-vocabulary.json under "assignment"; the GUI mirrors it.
FIELD = "assignment"

STATES = ["unclaimed", "held", "released", "expired", "resolved"]
#: What a writer may put on disk. The other two are read off the clock.
STORED_STATES = ["held", "released", "resolved"]
DERIVED_STATES = ["unclaimed", "expired"]

#: The same three words the upstream model uses, minus "missing": a claim that
#: ran out is "expired", not "missing".
FRESHNESS = ["fresh", "stale", "expired"]

#: Fraction of a lease that may be spent before it reads stale. A holder renews
#: on the far side of this, so a renewal is a heartbeat rather than a rewrite.
STALE_AFTER = 0.5

DEFAULT_TTL_MINUTES = 30

COMPANION_FIELDS = ["claimed_at", "ttl_minutes", "assignment_note", "assignment_note_by"]

#: Who a note is attributed to when the runtime wrote it rather than a person.
RUNTIME_AUTHOR = "runtime"

ATTENTION_OF_ASSIGNMENT = {
    "unclaimed": "needs_you",
    "held": "in_flight",
    "released": "needs_you",
    "expired": "needs_you",
    "resolved": "resolved",
}

#: Leases live on memories, because frontmatter has somewhere to put a stamp.
ASSIGNABLE_NAMESPACES = ["work"]

#: Why a row refuses a claim, in its own terms. Saying so beats pretending.
REFUSALS = {
    "episode": "an episode is a recorded negotiation, and there is nothing to assign",
    "agent": "presence is already a lease the runtime renews; it is not claimable",
    "memory": "assignments live on work/ memories; this row is in another namespace",
}

#: A row is blocked because it names a blocker. Nothing stores the word.
BLOCKED_FIELD = "blocked_by"


def parse_stamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def elapsed_fraction(stamped_at: str | None, ttl_minutes: Any, now: datetime) -> float | None:
    """Fraction of a lease already burned, or ``None`` when it cannot expire.

    A row with no TTL is not a lease — nobody has taken it for a window — so it
    has no fraction to report rather than a zero.
    """
    stamp = parse_stamp(stamped_at)
    try:
        ttl = float(ttl_minutes)
    except (TypeError, ValueError):
        return None
    if stamp is None or ttl <= 0:
        return None
    return max(0.0, (now - stamp).total_seconds() / 60.0 / ttl)


def freshness(stamped_at: str | None, ttl_minutes: Any, now: datetime) -> str | None:
    """fresh / stale / expired, in the shape the upstream half already reads."""
    fraction = elapsed_fraction(stamped_at, ttl_minutes, now)
    if fraction is None:
        return None
    if fraction < STALE_AFTER:
        return "fresh"
    return "stale" if fraction < 1.0 else "expired"


def claimed_at(item: LiveItem) -> str | None:
    """When the holder last said it was still on this.

    Falls back to when the row last moved: a hand-written ``owner:`` is still
    a claim, dated from the file's own update time.
    """
    return item.text("claimed_at") or item.text("updated")


def assignment_of(item: LiveItem, now: datetime) -> str | None:
    """The row's assignment state, or ``None`` when it has no assignment axis.

    ``None`` is not a state — it means this row is not the kind of thing anyone
    holds (a decision that has been made, a prose memory), so an attention filter must fall
    back to its stage rather than inventing a holder for it.

    A ``held`` lease whose clock ran out reads ``expired`` here, with nothing on
    disk having changed: the row drains because time passed, not because someone
    remembered to write it down.
    """
    stored = item.text(FIELD)
    if stored not in STATES:
        return None
    if stored != "held":
        return stored
    if not item.owner:
        # Held by nobody is not held. A row that lost its holder is in the pool.
        return "unclaimed"
    # A claim that cannot be shown to be alive is not evidence that it is. An
    # undatable one — no stamp, or no window to age it against — is the purest
    # form of the assertion this model refuses: held forever, by nobody's word.
    return (
        "held"
        if freshness(claimed_at(item), item.get("ttl_minutes"), now) in ("fresh", "stale")
        else "expired"
    )


def is_blocked(item: LiveItem) -> bool:
    """A row is blocked because it names a blocker, never because it says so."""
    return bool(item.strings(BLOCKED_FIELD))


def attention_of_item(item: LiveItem, now: datetime) -> str:
    """Which attention filter a row belongs on: assignment first, stage only where there is none.

    Blocked wins over both — a row waiting on something needs a person whoever
    is nominally holding it.
    """
    from mycelium.board.model import attention_of_status

    if is_blocked(item):
        return "needs_you"
    state = assignment_of(item, now)
    if state is not None:
        return ATTENTION_OF_ASSIGNMENT[state]
    return attention_of_status(item.status)


def note_of(item: LiveItem, now: datetime) -> tuple[str, str] | None:
    """The row's assignment note and who wrote it, or ``None`` when there is none.

    Handing work off deliberately and dying mid-task converge on the same state:
    an unclaimed row with history.  What tells them apart is the note's author —
    the releaser wrote one, the runtime wrote the other — so both come back
    together rather than as a line of text a reader has to interpret.
    """
    state = assignment_of(item, now)
    if state == "expired":
        holder = item.owner or "its holder"
        return (f"expired — @{holder} stopped renewing", RUNTIME_AUTHOR)
    note = item.text("assignment_note")
    if not note:
        return None
    return (note, item.text("assignment_note_by") or RUNTIME_AUTHOR)


def assignment_refusal(item: LiveItem) -> str | None:
    """Why this row cannot take a lease, or ``None`` when it can."""
    kind = item.source.kind
    if kind in ("episode", "agent"):
        return REFUSALS[kind]
    if kind == "memory":
        namespace = str(item.get("namespace") or item.source.label.split("/")[0])
        return None if namespace in ASSIGNABLE_NAMESPACES else REFUSALS["memory"]
    return REFUSALS["memory"]


def claim_patch(handle: str, now: datetime, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> dict:
    """The frontmatter a claim writes. One shape, whoever is doing the claiming."""
    return {
        FIELD: "held",
        "owner": handle if handle.startswith("@") else f"@{handle}",
        "claimed_at": now.isoformat(),
        "ttl_minutes": ttl_minutes,
        "assignment_note": None,
        "assignment_note_by": None,
    }


def release_patch(handle: str, now: datetime, note: str | None = None) -> dict:
    """The frontmatter a deliberate handoff writes: no holder, and a note saying so."""
    return {
        FIELD: "released",
        "owner": None,
        "claimed_at": None,
        "ttl_minutes": None,
        "assignment_note": note or "released",
        "assignment_note_by": handle.lstrip("@"),
        "updated": now.isoformat(),
    }


def remaining_minutes(item: LiveItem, now: datetime) -> int | None:
    """Minutes of lease left, or ``None`` when the row does not expire."""
    fraction = elapsed_fraction(claimed_at(item), item.get("ttl_minutes"), now)
    if fraction is None:
        return None
    try:
        ttl = float(item.get("ttl_minutes"))
    except (TypeError, ValueError):
        return None
    return max(0, int(round(ttl * (1.0 - fraction))))


def renew_patch(now: datetime) -> dict:
    """A heartbeat: the same lease, said again. Nothing about the row changes."""
    return {"claimed_at": now.isoformat()}
