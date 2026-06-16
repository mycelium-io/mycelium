# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``@handle`` mention resolution for room broadcasts.

Mirror of the openclaw plugin's ``mentions.ts``:

    Return the subset of *agents* that are ``@``-mentioned in *content*.
    Matches ``@agent-id`` as a word (case-insensitive). ``@julia-agent``
    matches; bare ``julia-agent`` does not — the ``@`` prefix is required.

The word-boundary check rejects suffixed handles (``@julia-agent-bot``
does not match ``julia-agent``), keeping the policy 1:1 with openclaw so
the same room can be mentioned identically from either family.
"""

from __future__ import annotations

import re

_WORD_TRAILER = re.compile(r"[a-z0-9_-]")


def resolve_mentions(content: str, agents: list[str]) -> list[str]:
    """Return agents @-mentioned in *content* in *agents*-list order."""
    if not content or not agents:
        return []
    lower = content.lower()
    out: list[str] = []
    for agent_id in agents:
        needle = f"@{agent_id.lower()}"
        idx = lower.find(needle)
        if idx == -1:
            continue
        # Word boundary: char after the handle must not be alnum/-/_.
        end = idx + len(needle)
        next_char = lower[end] if end < len(lower) else ""
        if next_char and _WORD_TRAILER.match(next_char):
            continue
        out.append(agent_id)
    return out
