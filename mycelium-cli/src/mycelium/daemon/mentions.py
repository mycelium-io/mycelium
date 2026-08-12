# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""@-mention parsing — resolve which registered handles a message addresses."""

from __future__ import annotations

import re

_TRAILING_CHAR = re.compile(r"[a-z0-9_-]")


def resolve_mentions(content: str, handles: list[str]) -> list[str]:
    """Return the subset of ``handles`` that are @-mentioned in ``content``."""
    lower = content.lower()
    hit: list[str] = []
    for handle in handles:
        needle = f"@{handle.lower()}"
        idx = lower.find(needle)
        if idx == -1:
            continue
        end = idx + len(needle)
        next_char = lower[end] if end < len(lower) else ""
        if next_char and _TRAILING_CHAR.match(next_char):
            continue
        hit.append(handle)
    return hit
