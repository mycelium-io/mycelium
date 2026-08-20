# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The shared keyset-pagination primitive (issue #654).

The properties every list route inherits from it: a cursor names a *key*, not a
position, so a page boundary survives rows arriving at the head and rows
vanishing underneath it — the two ways offset paging goes wrong on a live list.
"""

from datetime import UTC, datetime

import pytest

from app.services.pagination import (
    InvalidCursor,
    decode_cursor,
    encode_cursor,
    paginate,
    timestamp_key,
)


def _rows(n: int) -> list[tuple[str, str]]:
    """``n`` rows keyed (stamp, id), oldest first."""
    return [(f"2026-08-20T10:00:{i:02d}", f"id-{i:02d}") for i in range(n)]


def _key(row: tuple[str, str]) -> tuple[str, str]:
    return row


def _walk(rows, *, limit: int, mutate=None) -> list[tuple[str, str]]:
    """Page all the way through ``rows``, applying ``mutate`` between pages."""
    seen: list[tuple[str, str]] = []
    cursor: str | None = None
    while True:
        page = paginate(rows, key=_key, limit=limit, cursor=cursor)
        seen.extend(page.items)
        if not page.has_more:
            return seen
        cursor = page.next_cursor
        assert cursor is not None
        if mutate is not None:
            rows = mutate(rows)


def test_a_cursor_walk_covers_every_row_exactly_once():
    rows = _rows(10)
    walked = _walk(rows, limit=3)
    assert walked == sorted(rows, reverse=True)


def test_rows_arriving_at_the_head_neither_duplicate_nor_skip():
    """The reverse-scroll case: a busy room grows while the reader walks back.

    Under offset paging each new row shifts every later page by one; keyed on the
    boundary row instead, the walk is untouched by what lands at the head.
    """
    rows = _rows(10)
    fresh = iter([("2026-08-20T11:00:00", f"id-new-{i}") for i in range(5)])
    walked = _walk(rows, limit=3, mutate=lambda current: [*current, next(fresh)])
    assert walked == sorted(rows, reverse=True)


def test_deleting_the_boundary_row_still_resolves_the_next_page():
    """A cursor is a comparison, not a lookup — the row it names may be gone."""
    rows = _rows(6)
    first = paginate(rows, key=_key, limit=2)
    remaining = [r for r in rows if r != first.items[-1]]

    second = paginate(remaining, key=_key, limit=2, cursor=first.next_cursor)
    assert second.items == sorted(rows, reverse=True)[2:4]


def test_the_last_page_reports_no_more_and_no_cursor():
    page = paginate(_rows(4), key=_key, limit=10)
    assert len(page.items) == 4
    assert page.has_more is False
    assert page.next_cursor is None


def test_total_counts_the_whole_list_not_the_page():
    page = paginate(_rows(30), key=_key, limit=5)
    assert page.total == 30
    assert len(page.items) == 5


def test_offset_still_pages_when_no_cursor_is_given():
    """Back-compat: callers that haven't migrated keep their positional paging."""
    ordered = sorted(_rows(10), reverse=True)
    page = paginate(_rows(10), key=_key, limit=3, offset=6)
    assert page.items == ordered[6:9]


def test_a_cursor_wins_over_an_offset():
    ordered = sorted(_rows(10), reverse=True)
    first = paginate(_rows(10), key=_key, limit=4)
    page = paginate(_rows(10), key=_key, limit=4, cursor=first.next_cursor, offset=9)
    assert page.items == ordered[4:8]


def test_ascending_lists_walk_forward():
    ordered = sorted(_rows(7))
    first = paginate(_rows(7), key=_key, limit=3, descending=False)
    second = paginate(_rows(7), key=_key, limit=3, cursor=first.next_cursor, descending=False)
    assert first.items == ordered[:3]
    assert second.items == ordered[3:6]


def test_a_cursor_round_trips_its_key():
    assert decode_cursor(encode_cursor(("2026-08-20", "id-7"))) == ("2026-08-20", "id-7")


def test_a_cursor_token_is_opaque_and_url_safe():
    token = encode_cursor(("2026-08-20T10:00:00+00:00", "id/with?punctuation"))
    assert token == token.strip()
    assert not set(token) & set("+/= ")


@pytest.mark.parametrize("token", ["not base64!!", "eyJub3QiOiAibGlzdCJ9", "%%%"])
def test_a_malformed_cursor_is_rejected_rather_than_guessed(token):
    with pytest.raises(InvalidCursor):
        paginate(_rows(3), key=_key, limit=2, cursor=token)


def test_an_empty_cursor_reads_as_no_cursor():
    assert (
        paginate(_rows(3), key=_key, limit=2, cursor="").items == sorted(_rows(3), reverse=True)[:2]
    )


def test_timestamp_keys_sort_chronologically_across_offsets():
    """Two spellings of the same instant must compare equal, and an earlier
    instant must sort earlier — which raw ``isoformat`` text does not guarantee."""
    from datetime import timedelta, timezone

    utc = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
    elsewhere = utc.astimezone(timezone(timedelta(hours=-7)))
    assert timestamp_key(utc) == timestamp_key(elsewhere)
    assert timestamp_key(utc - timedelta(seconds=1)) < timestamp_key(utc)
    assert timestamp_key(datetime(2026, 8, 20, 10, 0, 0)) == timestamp_key(utc)


def test_a_naive_and_aware_stamp_do_not_crash_the_sort():
    """Message rows come from two stores; a mixed batch must still order."""
    rows = [
        ("naive", datetime(2026, 8, 20, 10, 0, 1)),
        ("aware", datetime(2026, 8, 20, 10, 0, 2, tzinfo=UTC)),
    ]
    page = paginate(rows, key=lambda r: (timestamp_key(r[1]), r[0]), limit=10)
    assert [r[0] for r in page.items] == ["aware", "naive"]
