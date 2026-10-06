# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What differs between the agent kinds herdr starts, looked up by kind.

Generic code asks here and never names a kind itself; a kind with something of
its own (arguments, wording for its prompts) has a module beside this one.
"""

from __future__ import annotations

from types import ModuleType

from mycelium.integrations.herdr import claude

_KINDS: dict[str, ModuleType] = {"claude": claude}


def agent_args(kind: str) -> list[str] | None:
    """Arguments ``kind`` is started with, or ``None`` for its defaults."""
    module = _KINDS.get(kind)
    return list(module.ARGS) if module is not None and hasattr(module, "ARGS") else None


def blocked_hint(kind: str) -> str | None:
    """A line on what ``kind`` is commonly waiting for when herdr reads it as blocked."""
    module = _KINDS.get(kind)
    hint = getattr(module, "blocked_hint", None)
    return hint() if callable(hint) else None
