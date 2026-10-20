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


def test_codex_sandbox_lets_mycelium_reach_the_hub_and_write_only_its_agent_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    args = agents.of_kind("codex").launch_args()
    state = tmp_path / ".mycelium" / "agent-state"
    assert args == ["-c", "sandbox_workspace_write.network_access=true", "--add-dir", str(state)]
    assert state.is_dir()
    # Never the whole folder: its config, herdr registry and the runner's
    # approval files stay out of an agent's reach.
    assert str(tmp_path / ".mycelium") not in args
    # Never the bypass, and never a change to who approves what.
    assert not any("dangerously" in a or a in ("-a", "--ask-for-approval") for a in args)


def test_what_an_agent_writes_lives_in_the_agent_state_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from mycelium import agent_credentials
    from mycelium.commands import participate
    from mycelium.config import MyceliumConfig

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(agent_credentials.CREDENTIAL_STORE_ENV, raising=False)
    state = MyceliumConfig.get_agent_state_dir()
    assert participate._pending_file().parent == state  # noqa: SLF001
    assert agent_credentials.token_cache_path("scout").is_relative_to(state)


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
