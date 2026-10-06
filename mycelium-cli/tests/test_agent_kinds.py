# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium.integrations.agents``: the one place an agent CLI is named."""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.integrations import agents, get_integration

PACKAGE = Path(agents.__file__).resolve().parents[2]


def test_each_cli_is_listed_once():
    ids = [k.id for k in agents.KNOWN]
    assert len(ids) == len(set(ids))


def test_a_cli_with_nothing_of_its_own_adds_nothing():
    codex = agents.of_kind("codex")
    assert codex.launch_args() == []
    assert codex.blocked_hint() is None
    unknown = agents.of_kind("someday")
    assert (unknown.id, unknown.launch_args(), unknown.adapter) == ("someday", [], "claude_code")


def test_claude_is_started_allowed_mycelium_and_says_what_it_waits_for():
    claude = agents.of_kind("claude")
    assert claude.launch_args() == ["--allowedTools", "Bash(mycelium:*)"]
    assert "Claude Code asks before" in (claude.blocked_hint() or "")


@pytest.mark.parametrize(
    ("framework", "adapter"),
    [
        ("cursor", "cursor"),
        ("claude", "claude_code"),
        ("codex", "claude_code"),
        (None, "claude_code"),
    ],
)
def test_each_cli_is_recorded_under_its_manifest_family(framework, adapter):
    assert agents.adapter_for(framework) == adapter
    assert get_integration(adapter).name == adapter


@pytest.mark.parametrize(
    "module",
    [
        "runner/hosts.py",
        "runner/daemon.py",
        "integrations/herdr/bridge.py",
        "commands/swarm.py",
        "machine.py",
    ],
)
def test_the_generic_paths_name_no_cli(module: str):
    text = (PACKAGE / module).read_text()
    for said in ("Claude Code", "--allowedTools", "Cursor Agent"):
        assert said not in text, f"{module} names {said!r}; it belongs in integrations/agents"
