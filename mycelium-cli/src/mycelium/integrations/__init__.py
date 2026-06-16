# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Integration registry — the single resolution point for a runtime family.

This package subsumes what used to be three colliding "adapter" things:

- ``mycelium.agent_adapters`` (the dispatch OOP layer) — folded into the
  per-family ``dispatch`` facet here; that package is deleted.
- the install pile in ``mycelium.commands.adapter`` — relocated into
  ``integrations/<family>/install.py``; the command layer is now a thin
  registry dispatcher.
- ``mycelium.adapters`` (the static asset bundle) — relocated to
  ``mycelium.integrations.<family>.assets/`` so the data lives with the one
  package that owns it.

One canonical family id is used everywhere internally — the **underscore**
spelling (``claude_code``), since that is the value persisted in
``agents/<handle>`` manifests and matched by the daemon dispatch guard and
``sstp.AGENT_ADAPTERS``. The **hyphen** spelling (``claude-code``) survives
only as the user-facing ``mycelium adapter add`` argument and the on-disk
asset directory name; :func:`normalize_family_id` is the one translation
boundary.
"""

from __future__ import annotations

from mycelium.integrations.base import AddOptions, AgentAdapter, Integration
from mycelium.integrations.claude_code import ClaudeCodeIntegration
from mycelium.integrations.cursor import CursorIntegration
from mycelium.integrations.hermes import HermesIntegration
from mycelium.integrations.openclaw import OpenClawIntegration

__all__ = [
    "AddOptions",
    "AgentAdapter",
    "Integration",
    "get_adapter",
    "get_integration",
    "normalize_family_id",
]

#: Presentation/legacy aliases → canonical underscore family id. The hyphen
#: form is the public CLI argument (`mycelium adapter add claude-code`) and the
#: asset directory name; everything internal uses the canonical value.
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
    openclaw_agent: str | None = None,
    model: str | None = None,
    openclaw_profile: str | None = None,
    copy_auth_from: str | None = None,
) -> Integration:
    """Return an integration instance for *name* (any accepted spelling).

    Family-specific `agent add` flags are passed through and bound to the
    instance so ``build_manifest``/``register`` keep a uniform signature. For
    non-add call sites (e.g. ``agent rm``) the extra kwargs are simply omitted
    — only ``openclaw_profile`` matters there and defaults to None.
    """
    canonical = normalize_family_id(name)
    if canonical == "claude_code":
        return ClaudeCodeIntegration(cwd=cwd)
    if canonical == "cursor":
        # cursor takes the same ``cwd`` flag claude_code does — it's the
        # workspace root ``cursor-agent --workspace`` opens. The openclaw
        # kwargs are silently ignored (kept on the factory signature so
        # ``commands/adapter.py`` can pass everything uniformly).
        return CursorIntegration(cwd=cwd)
    if canonical == "openclaw":
        return OpenClawIntegration(
            openclaw_agent=openclaw_agent,
            model=model,
            openclaw_profile=openclaw_profile,
            copy_auth_from=copy_auth_from,
        )
    if canonical == "hermes":
        # Hermes always targets whichever profile is active on the host
        # (``$HERMES_HOME`` or ``~/.hermes/``). First-class multi-profile
        # selection is on hold until ``hermes-agent#25660`` (single gateway,
        # multiple agents) lands — at which point handle-level routing
        # replaces per-profile gateways entirely.
        return HermesIntegration()
    raise ValueError(f"unknown integration: {name!r}")


#: Readability alias used by ``commands/agent.py`` ("get the adapter for this
#: handle"); identical behaviour to :func:`get_integration`.
get_adapter = get_integration
