"""The docs search index has to stay mergeable.

It is regenerated wholesale by every PR that touches the docs markdown, so its
on-disk shape decides whether two such branches can merge at all. As one long
line it was a single atom: git had nothing to align on and every pair of docs
branches conflicted across the whole 122KB.

The drift check in CI would not catch a regression here — a single-line dump is
still *current*, just unmergeable — so the shape is asserted directly, against
the committed artifact the generator produces.
"""

import json
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[2] / "docs" / "search-index.js"

OPENER = "window.MYCELIUM_SEARCH_INDEX = ["
CLOSER = "];"


@pytest.fixture(scope="module")
def lines() -> list[str]:
    if not INDEX.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip(f"{INDEX} not present")
    return INDEX.read_text().splitlines()


def test_index_brackets_are_on_their_own_lines(lines: list[str]) -> None:
    assert lines[0] == OPENER
    assert lines[-1] == CLOSER


def test_every_record_is_one_line(lines: list[str]) -> None:
    """One record per line is what lets git merge disjoint edits by itself."""
    records = lines[1:-1]
    assert records, "search index is empty"
    for i, line in enumerate(records):
        parsed = json.loads(line.rstrip(","))
        assert isinstance(parsed, dict), f"record {i} is not an object"
        assert parsed.get("u"), f"record {i} has no url"


def test_every_record_line_ends_in_a_comma(lines: list[str]) -> None:
    """Including the last one, which is what makes a union merge safe.

    `.gitattributes` resolves overlapping edits with git's union driver, which
    keeps both sides' lines. That only stays parseable if no line's syntax
    depends on being last: a trailing comma is legal in a JS array literal, and
    this file is a script, not JSON.
    """
    records = lines[1:-1]
    assert records, "search index is empty"
    for i, line in enumerate(records):
        assert line.endswith(","), f"record {i} does not end in a comma"


def test_union_merge_of_the_index_still_parses(lines: list[str]) -> None:
    """Duplicating every record stands in for the worst case a union can emit.

    A union merge can leave a record twice — both sides' version of one that
    each branch edited. The cost is a duplicated search hit until someone
    regenerates, which the docs drift check in CI makes them do. It must never
    be a syntax error that takes the whole index down.
    """
    unioned = [lines[0], *lines[1:-1], *lines[1:-1], lines[-1]]
    body = "\n".join(unioned).removeprefix(OPENER).removesuffix(CLOSER)
    records = json.loads(f"[{body.strip().rstrip(',')}]")
    assert len(records) == 2 * (len(lines) - 2)
