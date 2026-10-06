# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every agent CLI Mycelium knows, and what it knows about each, in one place.

The runner's scan, herdr and Omnigent starting an agent, ``mycelium swarm`` and
``mycelium agent create`` all ask here; nothing outside this package names a
CLI. A CLI with something of its own (arguments, wording for its prompts, files
its agents need) has a module beside this one; the rest are :class:`AgentKind`
as it is. Whether a CLI can be started is its host's call, never listed here.
"""

from __future__ import annotations

from mycelium.integrations.agents.base import AgentKind, ResidentIntegration
from mycelium.integrations.agents.claude import Claude
from mycelium.integrations.agents.cursor import Cursor, CursorIntegration

__all__ = [
    "KNOWN",
    "AgentKind",
    "CursorIntegration",
    "ResidentIntegration",
    "adapter_for",
    "by_id",
    "of_kind",
]

KNOWN: tuple[AgentKind, ...] = (
    Claude("claude", "Claude Code", ("claude",), "claude"),
    AgentKind("codex", "Codex", ("codex",), "codex"),
    AgentKind("gemini", "Gemini CLI", ("gemini",), "gemini"),
    Cursor("cursor", "Cursor Agent", ("cursor-agent",), "cursor"),
    AgentKind("opencode", "OpenCode", ("opencode",), "opencode"),
    AgentKind("pi", "Pi", ("pi",), "pi"),
    AgentKind("copilot", "GitHub Copilot CLI", ("copilot",), "copilot"),
    AgentKind("amp", "Amp", ("amp",), "amp"),
    AgentKind("droid", "Droid", ("droid",), "droid"),
    AgentKind("cline", "Cline", ("cline",), "cline"),
    AgentKind("kiro", "Kiro", ("kiro-cli", "kiro"), "kiro"),
    AgentKind("kimi", "Kimi", ("kimi",), "kimi"),
    AgentKind("grok", "Grok", ("grok",), "grok"),
    AgentKind("goose", "Goose", ("goose",), None),
    AgentKind("aider", "Aider", ("aider",), None),
)


def by_id(framework_id: str | None) -> AgentKind | None:
    """The CLI with this id (the manifest's ``framework``), if Mycelium knows it."""
    return next((k for k in KNOWN if k.id == framework_id), None)


def of_kind(kind: str | None) -> AgentKind:
    """The CLI herdr starts as ``kind`` (or with that id); one Mycelium adds nothing to otherwise."""
    found = next((k for k in KNOWN if kind and kind in (k.herdr_kind, k.id)), None)
    return found or AgentKind(kind or "", kind or "", (), kind)


def adapter_for(framework: str | None) -> str:
    """The manifest family an agent CLI's agents are recorded under.

    The hub's ``routes/runners.adapter_for`` answers the same for the agents it writes.
    """
    known = by_id(framework)
    return known.adapter if known else AgentKind.adapter
