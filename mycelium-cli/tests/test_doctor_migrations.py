# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Regression tests for ``mycelium doctor`` migration-check parsing.

Pre-Option-B, ``_check_pending_migrations`` did three things wrong:

1. Read the always-unset ``server.database_url`` config field, so alembic
   was invoked without a real DATABASE_URL and crashed with a Python
   traceback that included the substring ``Traceback``.
2. Concatenated alembic stdout + stderr before regex-matching, so the
   crash output flowed into the revision-extraction code path.
3. Used the loose regex ``([0-9a-f]{4,})`` which greedily matched the
   ``aceback`` tail of ``Traceback`` and reported it as the DB revision
   — the user-visible "DB at acebac, latest is 0016 — pending migrations"
   false positive (issue #287).

These tests pin down the post-fix parser contract so the regression
class can never sneak back in.
"""

from __future__ import annotations

from mycelium.commands.doctor import _parse_alembic_current

# ─── Happy path: real alembic-current outputs ────────────────────────────


def test_parses_mycelium_numeric_revision_with_head_label() -> None:
    """Mycelium uses 4-digit numeric prefixes; default alembic format."""
    stdout = "0016 (head)\n"
    assert _parse_alembic_current(stdout) == "0016"


def test_parses_bare_revision_without_head_label() -> None:
    stdout = "0008\n"
    assert _parse_alembic_current(stdout) == "0008"


def test_parses_stock_alembic_12char_hex_hash() -> None:
    """Stock alembic uses 12-char hex hashes; helper must accept those too."""
    stdout = "f3a1b2c4d5e6 (head)\n"
    assert _parse_alembic_current(stdout) == "f3a1b2c4d5e6"


def test_parses_revision_when_branched_with_labels() -> None:
    """alembic shows branch labels in parentheses after the rev."""
    stdout = "0014 (mybranch)\n"
    assert _parse_alembic_current(stdout) == "0014"


# ─── #287 regression: never parse tracebacks as revisions ───────────────


def test_traceback_substring_does_not_match() -> None:
    """Issue #287: 'Traceback' contains the 6-hex substring 'aceback'.

    If a caller ever leaks stderr into the parser, the function still must
    not return 'aceback' (or 'acebac', the original false-positive
    detected by the old loose regex) — that bug surfaced as
    "DB at acebac, latest is 0016 — pending migrations" in doctor output.
    """
    stderr_leak = (
        "Traceback (most recent call last):\n"
        '  File "env.py", line 28, in <module>\n'
        '    raise ValueError("DATABASE_URL environment variable is not set!")\n'
        "ValueError: DATABASE_URL environment variable is not set!\n"
    )
    result = _parse_alembic_current(stderr_leak)
    assert result != "acebac"
    assert result != "aceback"
    # Anchored regex requires start-of-line + word-boundary, so no spurious
    # hex token from inside the traceback should win.
    assert result is None or result.startswith("0") or len(result) >= 8, (
        f"unexpected token parsed from traceback: {result!r}"
    )


def test_alembic_info_log_line_does_not_match() -> None:
    """The log prefix '[alembic.runtime.migration]' contains hex chars
    but the anchored regex requires start-of-line + word-boundary, so
    it must not be picked up as a revision token.
    """
    log_only = (
        "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.\n"
        "INFO  [alembic.runtime.migration] Will assume transactional DDL.\n"
    )
    assert _parse_alembic_current(log_only) is None


# ─── Edge cases ──────────────────────────────────────────────────────────


def test_empty_stdout_returns_none() -> None:
    assert _parse_alembic_current("") is None


def test_whitespace_only_stdout_returns_none() -> None:
    assert _parse_alembic_current("   \n\t\n") is None


def test_revision_with_leading_whitespace_is_accepted() -> None:
    """Some alembic configurations indent the output; tolerate that."""
    stdout = "    0016 (head)\n"
    assert _parse_alembic_current(stdout) == "0016"


def test_revision_followed_by_branch_arrow() -> None:
    """alembic uses ' -> ' notation for branch heads."""
    stdout = "0015 -> 0016 (head)\n"
    assert _parse_alembic_current(stdout) == "0015"


def test_three_char_token_is_too_short() -> None:
    """alembic never emits 3-char revisions; demanding 4+ rules out a
    whole class of false-positives without losing real matches.
    """
    assert _parse_alembic_current("abc\n") is None


def test_uppercase_hex_is_rejected() -> None:
    """alembic always lowercases hex revisions; uppercase indicates noise."""
    assert _parse_alembic_current("ABCD1234\n") is None
