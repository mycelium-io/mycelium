# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Agent adapter registry.

``get_adapter()`` is the single entry point the command layer uses. Adding a
new runtime is: write an AgentAdapter subclass, add one ``elif`` here, extend
``sstp.AGENT_ADAPTERS`` + the ``AgentManifest.adapter`` Literal. The command
layer never changes.
"""

from __future__ import annotations

from mycelium.agent_adapters.base import AddOptions, AgentAdapter
from mycelium.agent_adapters.claude_code import ClaudeCodeAdapter
from mycelium.agent_adapters.openclaw import OpenClawAdapter

__all__ = ["AddOptions", "AgentAdapter", "get_adapter"]


def get_adapter(
    name: str,
    *,
    cwd: str | None = None,
    openclaw_agent: str | None = None,
    model: str | None = None,
    openclaw_profile: str | None = None,
) -> AgentAdapter:
    """Return an adapter instance for *name*.

    Adapter-specific `agent add` flags are passed through and bound to the
    instance so ``build_manifest``/``register`` keep a uniform signature.
    For non-add call sites (e.g. ``agent rm``) the extra kwargs are simply
    omitted — only ``openclaw_profile`` matters there and defaults to None.
    """
    if name == "claude_code":
        return ClaudeCodeAdapter(cwd=cwd)
    if name == "openclaw":
        return OpenClawAdapter(
            openclaw_agent=openclaw_agent,
            model=model,
            openclaw_profile=openclaw_profile,
        )
    raise ValueError(f"unknown adapter: {name!r}")
