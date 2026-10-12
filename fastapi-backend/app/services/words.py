# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Small rules for writing English about things whose names are only known at runtime."""

from __future__ import annotations


def a_or_an(word: str) -> str:
    """``word`` with "a" or "an" in front, picked by its first letter.

    The words this is used for are kinds the hub names itself (``action``,
    ``decision``, ``aligner``, ``persona``), so a vowel letter is a vowel sound
    and no list of exceptions is needed.
    """
    return f"{'an' if word[:1].lower() in 'aeiou' else 'a'} {word}"
