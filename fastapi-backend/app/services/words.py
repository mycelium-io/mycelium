# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Small rules for writing English about things whose names are only known at runtime."""

from __future__ import annotations


def a_or_an(word: str) -> str:
    """``word`` with "a" or "an" in front, picked by its first letter.

    The words this is used for are kinds the hub names itself (``action``,
    ``decision``, ``engine``, ``persona``), so a vowel letter is a vowel sound
    and no list of exceptions is needed.
    """
    vowel = bool(word) and word[0].lower() in "aeiou"
    return f"{'an' if vowel else 'a'} {word}"
