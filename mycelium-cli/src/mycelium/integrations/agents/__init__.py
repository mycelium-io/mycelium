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

_NPM = "npm install -g"

KNOWN: tuple[AgentKind, ...] = (
    Claude("claude", "Claude Code", ("claude",), "claude", f"{_NPM} @anthropic-ai/claude-code"),
    AgentKind("codex", "Codex", ("codex",), "codex", f"{_NPM} @openai/codex"),
    AgentKind("gemini", "Gemini CLI", ("gemini",), "gemini", f"{_NPM} @google/gemini-cli"),
    Cursor(
        "cursor",
        "Cursor Agent",
        ("cursor-agent",),
        "cursor",
        "curl -fsS https://cursor.com/install | bash",
    ),
    AgentKind("opencode", "OpenCode", ("opencode",), "opencode", f"{_NPM} opencode-ai"),
    AgentKind("pi", "Pi", ("pi",), "pi", f"{_NPM} @earendil-works/pi-coding-agent"),
    AgentKind("copilot", "GitHub Copilot CLI", ("copilot",), "copilot", f"{_NPM} @github/copilot"),
    AgentKind("amp", "Amp", ("amp",), "amp", f"{_NPM} @sourcegraph/amp"),
    AgentKind("droid", "Droid", ("droid",), "droid", "curl -fsSL https://app.factory.ai/cli | sh"),
    AgentKind("cline", "Cline", ("cline",), "cline", f"{_NPM} cline"),
    AgentKind(
        "kiro",
        "Kiro",
        ("kiro-cli", "kiro"),
        "kiro",
        "curl -fsSL https://cli.kiro.dev/install | bash",
    ),
    AgentKind(
        "kimi",
        "Kimi",
        ("kimi",),
        "kimi",
        "curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash",
    ),
    # Runs on bun, which its package doesn't bring with it.
    AgentKind(
        "grok",
        "Grok",
        ("grok",),
        "grok",
        "curl -fsSL https://bun.sh/install | bash && ~/.bun/bin/bun add -g grok-dev",
    ),
    AgentKind(
        "goose",
        "Goose",
        ("goose",),
        None,
        "curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh"
        " | CONFIGURE=false bash",
    ),
    AgentKind("aider", "Aider", ("aider",), None, "uv tool install --python 3.12 aider-chat"),
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
