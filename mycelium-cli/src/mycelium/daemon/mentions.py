# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""@-mention parsing — Python port of the OpenClaw plugin's resolveMentions."""

from __future__ import annotations

import re

_TRAILING_CHAR = re.compile(r"[a-z0-9_-]")


def resolve_mentions(content: str, handles: list[str]) -> list[str]:
    """Return the subset of ``handles`` that are @-mentioned in ``content``.

    Mirrors the TypeScript implementation in
    ``integrations/openclaw/assets/.../channel/mentions.ts`` so both gateways
    agree on which agent a message addresses.
    """
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
