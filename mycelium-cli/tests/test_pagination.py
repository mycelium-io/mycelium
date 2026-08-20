# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The client-side page walker (issue #654).

Every list on the hub pages the same way, so one walker drives all of them. What
it owes its callers: every row, in page order, and a guaranteed stop — a walk
that spins forever on a server quirk is worse than a short read.
"""

from mycelium.pagination import cursor_from_headers, walk_pages


def _pages(*pages: list[str]):
    """A fetcher serving ``pages`` in order, each cursor naming the next."""
    served: list[str | None] = []

    def fetch(cursor: str | None):
        served.append(cursor)
        index = 0 if cursor is None else int(cursor)
        rows = pages[index] if index < len(pages) else []
        return rows, str(index + 1) if index + 1 < len(pages) else None

    return fetch, served


def test_a_walk_returns_every_row_in_page_order():
    fetch, served = _pages(["a", "b"], ["c", "d"], ["e"])

    assert walk_pages(fetch) == ["a", "b", "c", "d", "e"]
    assert served == [None, "1", "2"]


def test_a_single_page_costs_a_single_request():
    fetch, served = _pages(["only"])

    assert walk_pages(fetch) == ["only"]
    assert served == [None]


def test_an_empty_list_walks_to_nothing():
    fetch, _served = _pages([])

    assert walk_pages(fetch) == []


def test_a_cursor_that_never_advances_ends_the_walk():
    """A server that keeps handing back the same cursor costs one wasted page,
    not an unbounded loop."""
    calls: list[str | None] = []

    def fetch(cursor: str | None):
        calls.append(cursor)
        return ["row"], "stuck"

    assert walk_pages(fetch) == ["row", "row"]
    assert calls == [None, "stuck"]


def test_a_walk_is_bounded_even_if_every_cursor_is_new():
    calls: list[str | None] = []

    def fetch(cursor: str | None):
        calls.append(cursor)
        return ["row"], f"c{len(calls)}"

    assert len(walk_pages(fetch, max_pages=5)) == 5


def test_headers_carry_the_cursor_of_a_bare_list_response():
    assert cursor_from_headers({"x-has-more": "true", "x-next-cursor": "c1"}) == "c1"


def test_the_last_page_of_a_bare_list_reports_no_cursor():
    assert cursor_from_headers({"x-has-more": "false", "x-next-cursor": "c1"}) is None
    assert cursor_from_headers({}) is None


def test_a_walk_can_resume_from_someone_else_s_cursor():
    """A script that stopped mid-history picks up exactly where it left off."""
    fetch, served = _pages(["a"], ["b"], ["c"])

    assert walk_pages(fetch, start="1") == ["b", "c"]
    assert served == ["1", "2"]
