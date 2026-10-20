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
    gemini = agents.of_kind("gemini")
    assert gemini.launch_args() == []
    assert gemini.blocked_hint() is None
    unknown = agents.of_kind("someday")
    assert (unknown.id, unknown.launch_args(), unknown.adapter) == ("someday", [], "claude_code")


def test_claude_is_started_allowed_mycelium_and_says_what_it_waits_for():
    claude = agents.of_kind("claude")
    assert claude.launch_args() == ["--allowedTools", "Bash(mycelium:*)"]
    assert "Claude Code asks before" in (claude.blocked_hint() or "")


def test_codex_sandbox_lets_mycelium_reach_the_hub_and_write_its_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    args = agents.of_kind("codex").launch_args()
    assert args == [
        "-c",
        "sandbox_workspace_write.network_access=true",
        "--add-dir",
        str(tmp_path / ".mycelium"),
    ]
    # Never the bypass, and never a change to who approves what.
    assert not any("dangerously" in a or a in ("-a", "--ask-for-approval") for a in args)


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
