# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Integration registry: the single resolution point for a runtime family.

Each family implements an :class:`Integration` subclass that builds, registers
and destroys agent manifests. The agent CLIs' families (``claude_code``,
``cursor``) live with everything else known about each CLI, in
:mod:`mycelium.integrations.agents`; ``engine`` and ``a2a`` are members that
are not CLIs and have packages of their own.

One canonical family id is used everywhere internally: the **underscore**
spelling (``claude_code``), since that is the value persisted in
``agents/<handle>`` manifests and matched by ``sstp.AGENT_ADAPTERS``. The
**hyphen** spelling (``claude-code``) is accepted from people, as
``agent create --adapter claude-code``; :func:`normalize_family_id` is the
one translation boundary.
"""

from __future__ import annotations

from mycelium.integrations.a2a import A2aIntegration
from mycelium.integrations.agents import CursorIntegration, ResidentIntegration, adapter_for
from mycelium.integrations.base import AddOptions, AgentAdapter, Integration
from mycelium.integrations.engine import EngineIntegration

__all__ = [
    "A2aIntegration",
    "AddOptions",
    "AgentAdapter",
    "Integration",
    "adapter_for",
    "get_adapter",
    "get_integration",
    "normalize_family_id",
]

#: Presentation/legacy aliases → canonical underscore family id. The hyphen
#: form is what people type (`agent create --adapter claude-code`); everything
#: internal uses the canonical value.
_FAMILY_ALIASES: dict[str, str] = {
    "claude-code": "claude_code",
}


def normalize_family_id(name: str) -> str:
    """Map any accepted spelling of a family id to its canonical form.

    The one translation boundary between the user-facing/asset hyphen spelling
    and the persisted underscore spelling. Unknown names pass through
    unchanged so callers can raise their own "unknown family" error with the
    original string.
    """
    return _FAMILY_ALIASES.get(name, name)


def get_integration(
    name: str,
    *,
    cwd: str | None = None,
    engine_kind: str | None = None,
    card: str | None = None,
) -> Integration:
    """Return an integration instance for *name* (any accepted spelling).

    Family-specific `agent add` flags are passed through and bound to the
    instance so ``build_manifest``/``register`` keep a uniform signature. For
    non-add call sites (e.g. ``agent rm``) the extra kwargs are simply omitted.
    """
    canonical = normalize_family_id(name)
    if canonical == "claude_code":
        return ResidentIntegration(cwd=cwd)
    if canonical == "cursor":
        # cursor takes the same ``cwd`` flag claude_code does; it's the
        # workspace root ``cursor-agent --workspace`` opens.
        return CursorIntegration(cwd=cwd)
    if canonical == "engine":
        # First-party cognition-engine family; ``engine_kind`` selects the CE
        # (aligner today). The other kwargs are irrelevant here.
        return EngineIntegration(kind=engine_kind)
    if canonical == "a2a":
        # External Agent2Agent endpoint; ``card`` locates its Agent Card. The
        # backend resolves it and holds the seat.
        return A2aIntegration(card=card)
    raise ValueError(f"unknown integration: {name!r}")


#: Readability alias used by ``commands/agent.py`` ("get the adapter for this
#: handle"); identical behavior to :func:`get_integration`.
get_adapter = get_integration
