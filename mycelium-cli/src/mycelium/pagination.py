# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Walking a paginated list from the client side.

The hub pages every list the same way (``app/services/pagination.py``): you ask
with a ``cursor``, you get back a page plus the ``next_cursor`` that continues
it, and a null cursor means you reached the end. Because the cursor names a row
rather than a position, a walk stays coherent while the room keeps talking —
which is the whole reason a script can page backward through live history at all.

That sameness is what this module trades on: give :func:`walk_pages` a function
that fetches one page, and it walks any list on the hub.

    rows = walk_pages(lambda cursor: fetch_one_page(cursor), limit=200)

Two response shapes carry the same two values: an envelope (``next_cursor`` /
``has_more`` in the body) or a bare list (the ``X-Next-Cursor`` / ``X-Has-More``
headers). :func:`cursor_from_headers` reads the second one.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping

import typer

# One page of a list: the rows, and the cursor that continues past them.
type PageFetcher[T] = Callable[[str | None], tuple[list[T], str | None]]

# Shared flags, so walking back reads the same on every command that lists.
CursorOption = typer.Option(
    None, "--cursor", help="Continue from a previous page's next_cursor (walk further back)"
)
AllOption = typer.Option(
    False, "--all", help="Walk every page to the end of history, not just the first"
)

# A walk stops here rather than spinning forever if a server ever hands back a
# cursor that doesn't advance. Generous: at the CLI's page sizes this is far more
# history than any room holds.
MAX_PAGES = 1000


def walk_pages[T](
    fetch: PageFetcher[T], *, start: str | None = None, max_pages: int = MAX_PAGES
) -> list[T]:
    """Follow ``next_cursor`` from ``start`` to the end of the list, in page order.

    ``fetch`` takes a cursor (None for the first page) and returns that page's
    rows plus the cursor after them. ``start`` resumes a walk someone else began.
    A repeated or empty cursor ends it, so a server that stops advancing costs
    one wasted page, not an infinite loop.
    """
    rows: list[T] = []
    cursor: str | None = start
    seen: set[str] = set()
    for _ in range(max_pages):
        page, cursor = fetch(cursor)
        rows.extend(page)
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    return rows


def cursor_from_headers(headers: MutableMapping[str, str]) -> str | None:
    """The next-page cursor of a bare-list response, or None at the end of it."""
    if headers.get("x-has-more", "false").lower() != "true":
        return None
    return headers.get("x-next-cursor") or None
