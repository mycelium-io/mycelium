"""Helpers for parsing scenario matrix rows.

Scenario YAML uses **roles** (logical participant labels like ``alpha``)
that may map to different **handles** at runtime (e.g. ``agent-alpha``).
"""

from __future__ import annotations

from typing import Any


def agent_role(agent: dict[str, Any]) -> str:
    """Return the logical role from a row ``agents[]`` entry."""
    role = agent.get("role")
    if isinstance(role, str) and role:
        return role
    handle = agent.get("handle")
    if isinstance(handle, str) and handle:
        return handle
    raise ValueError("scenario agent entry missing `role`")


def memory_write_role(entry: dict[str, Any], *, default_role: str) -> str:
    """Return which agent role performs a ``memory_writes[]`` entry."""
    role = entry.get("role")
    if isinstance(role, str) and role:
        return role
    handle = entry.get("handle")
    if isinstance(handle, str) and handle:
        return handle
    return default_role
