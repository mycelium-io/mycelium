# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The article in front of a kind the hub names at runtime."""

from __future__ import annotations

import pytest

from app.services.words import a_or_an


@pytest.mark.parametrize(
    ("word", "said"),
    [
        ("aligner", "an aligner"),
        ("action", "an action"),
        ("Engine", "an Engine"),
        ("decision", "a decision"),
        ("persona", "a persona"),
        ("worker", "a worker"),
    ],
)
def test_a_vowel_gets_an_and_anything_else_gets_a(word: str, said: str) -> None:
    assert a_or_an(word) == said
