# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Keyset (cursor) pagination, shared by every list route.

A cursor is an **opaque token carrying the sort key of the row a page ended
on** — not a position. The next page is "every row that sorts strictly past
this key", so pages stay stable while the list grows at the head: new rows
arriving while a client walks backward through history shift no offset, and a
row deleted mid-walk doesn't skip its neighbour (the comparison still
resolves, the row is simply gone).

That property is why this exists. Offset paging is fine for a frozen list and
wrong for a live one — reverse-scrolling a busy room duplicates and skips rows
between pages.

Using it takes two things: a **key function** returning a tuple of strings that
totally orders the rows (end it with an id so ties can't collapse), and a
direction. :func:`timestamp_key` renders a datetime as a fixed-width UTC string
so lexicographic comparison matches chronological order.

    page = paginate(rows, key=lambda m: (timestamp_key(m.created_at), str(m.id)),
                    limit=50, cursor=cursor)
    return {"messages": page.items, "total": page.total,
            "next_cursor": page.next_cursor, "has_more": page.has_more}

Routes expose the same three names everywhere — ``cursor`` in, ``next_cursor``
and ``has_more`` out — so one client-side walker drives any list. ``next_cursor``
continues in the list's own traversal direction: for a newest-first list that is
older rows, which is what a reverse scroll wants.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

T = TypeVar("T")

CursorKey = tuple[str, ...]

# Bumped only if the token payload shape changes; an older token then decodes to
# None and the route serves page one rather than 400-ing a client mid-scroll.
_CURSOR_VERSION = 1


class InvalidCursor(ValueError):
    """A cursor token that isn't one we minted (routes map this to 400)."""


def encode_cursor(key: Sequence[str]) -> str:
    """Render a sort key as the opaque token clients echo back."""
    raw = json.dumps([_CURSOR_VERSION, list(key)], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> CursorKey:
    """Recover the sort key a token carries.

    Raises :class:`InvalidCursor` for anything malformed. A token from a
    superseded version decodes to ``()`` — the caller reads that as "no cursor"
    and serves the first page.
    """
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        version, key = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise InvalidCursor(f"malformed cursor: {token!r}") from exc
    if version != _CURSOR_VERSION:
        return ()
    if not isinstance(key, list) or not all(isinstance(part, str) for part in key):
        raise InvalidCursor(f"malformed cursor: {token!r}")
    return tuple(key)


def timestamp_key(value: datetime | str | None) -> str:
    """A datetime as a fixed-width UTC string that sorts lexicographically.

    ``isoformat`` is not safe to compare as text — the offset suffix and
    optional microseconds make two equal instants order arbitrarily — so
    normalize to UTC and one fixed shape. A string comes back unchanged (a
    stored ISO stamp, already the room's own ordering) and None sorts first.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    moment = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return moment.strftime("%Y%m%dT%H%M%S.%f")


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of a list, plus what a client needs to ask for the next."""

    items: list[T]
    next_cursor: str | None
    has_more: bool
    total: int


def paginate(
    rows: Sequence[T],
    *,
    key: Callable[[T], Sequence[str]],
    limit: int,
    cursor: str | None = None,
    offset: int = 0,
    descending: bool = True,
) -> Page[T]:
    """Sort ``rows`` by ``key`` and return the page that follows ``cursor``.

    ``descending`` is the list's natural traversal direction (newest first for
    a transcript); ``next_cursor`` always continues that way. ``offset`` is the
    legacy positional path, honored only when no cursor is given, so callers
    that haven't migrated keep working.
    """
    ordered = sorted(rows, key=lambda row: tuple(key(row)), reverse=descending)
    total = len(ordered)

    start = 0
    if cursor:
        anchor = decode_cursor(cursor)
        if anchor:
            # Comparison, not position: the page starts at the first row sorting
            # strictly past the anchor, whether or not the anchor's row survives.
            start = next(
                (
                    i
                    for i, row in enumerate(ordered)
                    if (tuple(key(row)) < anchor if descending else tuple(key(row)) > anchor)
                ),
                total,
            )
    elif offset:
        start = min(offset, total)

    items = list(ordered[start : start + limit])
    has_more = start + len(items) < total
    next_cursor = encode_cursor(key(items[-1])) if items and has_more else None
    return Page(items=items, next_cursor=next_cursor, has_more=has_more, total=total)
