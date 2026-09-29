# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A person's name beside their handle, wherever the CLI prints who said something.

A message carries its sender's handle; the name is the one the person gave
themselves (the app asks on first load, ``mycelium iam --name`` sets it), kept
in the hub's user records. It is looked up when a message is printed, so a
rename shows everywhere at once, and a handle with no name prints as before.
"""

from __future__ import annotations

import time

# How long a lookup is trusted before a miss tries the hub again, so a watch
# left running picks up someone who named themselves after it started.
_REFRESH_S = 60.0

_names: dict[str, str] | None = None
_fetched_at = 0.0


def _load() -> dict[str, str]:
    try:
        from mycelium.commands.user import list_users

        return {
            u.handle.lower(): u.display_name.strip() for u in list_users() if u.display_name.strip()
        }
    except Exception:
        # A hub that can't list users still has messages worth reading.
        return {}


def name_of(handle: str) -> str | None:
    """The name ``handle`` gave themselves, or None."""
    global _names, _fetched_at
    key = handle.strip().lstrip("@").lower()
    now = time.monotonic()
    if _names is None or (key not in _names and now - _fetched_at > _REFRESH_S):
        _names = _load()
        _fetched_at = now
    return _names.get(key)


def who(handle: str) -> str:
    """``Julia Valenti (@julia)`` for someone with a name, else the handle as it was."""
    name = name_of(handle)
    return f"{name} (@{handle.strip().lstrip('@')})" if name else handle


def reset() -> None:
    """Forget what was looked up (for tests)."""
    global _names, _fetched_at
    _names = None
    _fetched_at = 0.0
