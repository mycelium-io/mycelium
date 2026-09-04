# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a board action's write may land.

An action that is not an assignment writes frontmatter, and only a memory has any.  The
rest of the board is projected out of state living elsewhere — a checklist
line, an episode record, a presence lease — so there is nothing to write onto,
and saying that beats accepting a change that goes nowhere.

Frozen in ``contracts/board-vocabulary.json`` under ``fields``; the GUI carries
its own copy and ``tests/test_board_fields.py`` asserts this one against that
file, so neither can drift alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium.board.assignment import COMPANION_FIELDS, FIELD

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mycelium.board.model import LiveItem

#: The only row kind with frontmatter behind it.
WRITABLE_SOURCE_KINDS = ["memory"]

#: Why a row refuses a field write, in its own terms.
REFUSALS = {
    "episode": "an episode is a recorded negotiation, not a row the room can edit",
    "agent": "presence is what the runtime reports, not a field you set",
    "capture": "this row is not in the room yet; capture it first",
    "github": "this value belongs to the tool it came from; change it there",
}

#: Assignment's own keys, derived from the lease model. A field write cannot
#: enforce lease rules (a live claim is not stealable, expiry reads off a clock).
RESERVED_FIELDS = [FIELD, "owner", *COMPANION_FIELDS]


def memory_key_of(item: LiveItem) -> str | None:
    """The memory key behind a row, or ``None`` when the row is not a memory."""
    if item.source.kind not in WRITABLE_SOURCE_KINDS:
        return None
    return item.id.split(":", 1)[1] if ":" in item.id else item.id


def field_write_refusal(item: LiveItem) -> str | None:
    """Why this row cannot take a field write, or ``None`` when it can."""
    kind = item.source.kind
    if kind in WRITABLE_SOURCE_KINDS:
        return None
    return REFUSALS.get(kind, "this row has no frontmatter to write")


def reserved_in(names: Iterable[str]) -> list[str]:
    """Which of ``names`` a lease owns, so a caller can refuse before writing."""
    return sorted(set(names) & set(RESERVED_FIELDS))
