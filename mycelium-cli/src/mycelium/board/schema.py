# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Infer a typed schema from a set of frontmatter bags.

Nothing declares the columns: the shape of a namespace is read back out of what
the markdown already carries, so a room that starts writing an ``assignee``
field gets an assignee column with no migration and no config.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mycelium.board.assignment import STATES as ASSIGNMENT_STATES
from mycelium.board.model import KINDS, PRIORITIES, STATUSES, LiveItem
from mycelium.board.upstream import UPSTREAM_STATES

#: Vocabularies the coordination layer defines rather than discovers.  Inference
#: wants a value to repeat before calling a field an enum — right for a room's
#: own fields, wrong for these, where a board must offer every column even when
#: a small room happens to use each state once.
KNOWN_VOCABULARIES: dict[str, list[str]] = {
    "status": STATUSES,
    "assignment": ASSIGNMENT_STATES,
    "kind": KINDS,
    "priority": PRIORITIES,
    "ci": ["green", "running", "red"],
    "upstream": UPSTREAM_STATES,
}

PREFERRED_ORDER = [
    "status",
    "assignment",
    "kind",
    "owner",
    "priority",
    "upstream",
    "ci",
    "branch",
    "pr",
    "issue",
    "blocks",
    "blocked_by",
    "tags",
    "updated",
    "ttl_minutes",
]

MAX_SELECT_CARDINALITY = 12

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}|$)")
_HANDLE = re.compile(r"^@[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
#: A URL, a memory reference, an issue number, or an owner/repo slug. Kept
#: identical to the GUI's copy: the same frontmatter has to read as the same
#: column on both surfaces or grouping and sorting disagree.
_LINKISH = re.compile(r"^(https?://|myc://|#\d+|[a-z0-9._-]+/[a-z0-9._/-]+$)", re.IGNORECASE)


@dataclass
class FieldSchema:
    name: str
    label: str
    type: str
    options: list[tuple[str, int]] = field(default_factory=list)
    filled: int = 0
    total: int = 0


def humanize(name: str) -> str:
    spaced = re.sub(r"[_-]+", " ", name).strip()
    return spaced[:1].upper() + spaced[1:] if spaced else name


def _is_number(text: str) -> bool:
    """A string that is really a number, so ``port: "8000"`` sorts numerically."""
    try:
        float(text)
    except ValueError:
        return False
    return True


def _classify(name: str, values: list[Any]) -> str:
    present = [v for v in values if v not in (None, "")]
    if not present:
        return "text"

    vocabulary = KNOWN_VOCABULARIES.get(name)
    if vocabulary and all(isinstance(v, str) and v in vocabulary for v in present):
        return "select"

    if all(isinstance(v, bool) for v in present):
        return "checkbox"
    if any(isinstance(v, list) for v in present):
        return "tags"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return "number"

    strings = [v for v in present if isinstance(v, str)]
    if len(strings) != len(present):
        return "text"
    if all(_ISO_DATE.match(s) for s in strings):
        return "date"
    if all(_HANDLE.match(s) for s in strings):
        return "handle"
    if all(_is_number(s) for s in strings):
        return "number"

    distinct = set(strings)
    repeats = len(strings) > len(distinct)
    shortish = all(len(s) <= 24 for s in distinct)
    if len(distinct) <= MAX_SELECT_CARDINALITY and repeats and shortish:
        return "select"
    if all(_LINKISH.match(s) for s in strings):
        return "link"
    return "text"


def _options(name: str, values: list[Any], type_: str) -> list[tuple[str, int]]:
    if type_ not in ("select", "handle", "tags", "checkbox"):
        return []
    counts: dict[str, int] = {}
    # A known vocabulary seeds its own zero-count options, so a column nothing is
    # in yet is still a column you can move work into.
    for value in KNOWN_VOCABULARIES.get(name, []):
        counts[value] = 0

    def bump(value: Any) -> None:
        if value in (None, ""):
            return
        counts[str(value)] = counts.get(str(value), 0) + 1

    for value in values:
        if isinstance(value, list):
            for entry in value:
                bump(entry)
        else:
            bump(value)

    vocabulary = KNOWN_VOCABULARIES.get(name)
    if vocabulary:
        # A defined vocabulary keeps its own order (open → resolved reads as a
        # pipeline); a discovered one sorts by how much the room uses it.
        return sorted(
            # A value outside the vocabulary sorts after every value in it: the
            # vocabulary is a deliberate order (open reads through to resolved),
            # and something unexpected does not belong in the middle of it.
            counts.items(),
            key=lambda kv: vocabulary.index(kv[0]) if kv[0] in vocabulary else len(vocabulary),
        )
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def infer_schema(items: list[LiveItem]) -> list[FieldSchema]:
    """The schema of a collection: one pass over every record's frontmatter."""
    by_name: dict[str, list[Any]] = {}
    for item in items:
        for name, value in item.fields.items():
            by_name.setdefault(name, []).append(value)

    fields: list[FieldSchema] = []
    for name, values in by_name.items():
        type_ = _classify(name, values)
        fields.append(
            FieldSchema(
                name=name,
                label=humanize(name),
                type=type_,
                options=_options(name, values, type_),
                filled=sum(1 for v in values if v not in (None, "")),
                total=len(items),
            )
        )

    def order(f: FieldSchema) -> tuple[int, int, str]:
        if f.name in PREFERRED_ORDER:
            return (0, PREFERRED_ORDER.index(f.name), f.name)
        return (1, -f.filled, f.name)

    return sorted(fields, key=order)


def groupable_fields(schema: list[FieldSchema]) -> list[FieldSchema]:
    """Fields a board can turn into columns: a bounded vocabulary, ≥2 values."""
    return [f for f in schema if f.type in ("select", "handle", "checkbox") and len(f.options) >= 2]
