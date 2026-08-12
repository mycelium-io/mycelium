# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the live ``mycelium demo`` orchestration.

The demo is glue over the real CLI: it discovers scenarios/personas from the
public agent-personas dataset, creates a room and agents, and seeds a
negotiation. These tests mock the network and subprocess calls — no real
backend, adapter, LLM, or GitHub access is touched.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import demo

runner = CliRunner()

# A fake slice of the agent-personas repo tree.
_FAKE_TREE = [
    "profiles/ex07_investment_portfolio/growth_agent.yaml",
    "profiles/ex07_investment_portfolio/risk_agent.yaml",
    "profiles/ex07_investment_portfolio/execution_agent.yaml",
    "profiles/ex02_inbox_thread_workflow/bob.yaml",
    "profiles/ex02_inbox_thread_workflow/julie.yaml",
    "preferences/ex07_growth_agent.yaml",
    "missions.yaml",
]


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


# ── discovery ───────────────────────────────────────────────────────────────────


def test_list_scenarios_from_tree() -> None:
    ids = demo._list_scenarios(_FAKE_TREE)
    assert ids == ["ex02_inbox_thread_workflow", "ex07_investment_portfolio"]


def test_pretty_topic() -> None:
    assert demo._pretty_topic("ex07_investment_portfolio") == "investment portfolio"
    assert demo._pretty_topic("default") == "default"


def test_resolve_scenario_derives_agents_and_persona_paths() -> None:
    """Handles come from profile filenames; persona paths from persona_parts."""
    profile_yaml = (
        "persona_parts:\n"
        "  - personas/preferences/ex07_growth_agent.yaml\n"
        "  - personas/strategies/negotiate_v1_0.yaml\n"
    )

    class FakeResp:
        text = profile_yaml

        def raise_for_status(self) -> None:  # noqa: D401
            return None

    with (
        patch.object(demo, "_fetch_tree", return_value=_FAKE_TREE),
        patch("httpx.get", return_value=FakeResp()),
    ):
        spec = demo._resolve_scenario("ex07_investment_portfolio")

    assert spec["id"] == "ex07_investment_portfolio"
    assert spec["title"] == "Investment portfolio"
    assert spec["room"] == "demo-investment-portfolio"
    handles = [a["handle"] for a in spec["agents"]]
    assert handles == ["execution", "growth", "risk"]  # sorted by profile filename
    # persona_parts' `personas/` prefix is translated to a repo-root path.
    for a in spec["agents"]:
        assert a["persona"] == "preferences/ex07_growth_agent.yaml"


def test_resolve_unknown_scenario_exits() -> None:
    with patch.object(demo, "_fetch_tree", return_value=_FAKE_TREE), pytest.raises(typer.Exit):
        demo._resolve_scenario("nope")


# ── argument / prereq gating ────────────────────────────────────────────────────


def test_list_command() -> None:
    with patch.object(demo, "_list_scenarios", return_value=["ex07_investment_portfolio"]):
        result = runner.invoke(app, ["demo", "--list"])
    assert result.exit_code == 0
    assert "ex07_investment_portfolio" in result.stdout


def test_adapter_required() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 1
    assert "--adapter is required" in result.stdout


def test_unknown_adapter_rejected() -> None:
    result = runner.invoke(app, ["demo", "--adapter", "nope"])
    assert result.exit_code == 1
    assert "Unknown adapter" in result.stdout


def test_blocks_when_prereqs_missing() -> None:
    """Missing adapter/LLM/backend should fail fast with fixes, not provision."""
    spec = {
        "id": "x",
        "title": "X",
        "topic": "x",
        "room": "demo-x",
        "task": "t",
        "agents": [{"handle": "a", "persona": "p"}, {"handle": "b", "persona": "p"}],
    }
    with (
        patch.object(demo, "_resolve_scenario", return_value=spec),
        patch.object(
            demo,
            "_check_prereqs",
            return_value=(object(), ["Adapter 'claude_code' is not installed."]),
        ),
        patch.object(demo, "_provision") as prov,
    ):
        result = runner.invoke(app, ["demo", "--adapter", "claude_code", "--yes"])
    assert result.exit_code == 1
    assert "Can't run the live demo yet" in result.stdout
    prov.assert_not_called()


# ── provisioning sequence ───────────────────────────────────────────────────────


def _spec() -> dict:
    return {
        "id": "ex07_investment_portfolio",
        "title": "Investment portfolio",
        "topic": "investment portfolio",
        "room": "demo-investment-portfolio",
        "task": "Reach consensus.",
        "agents": [
            {"handle": "growth", "persona": "preferences/ex07_growth_agent.yaml"},
            {"handle": "risk", "persona": "preferences/ex07_risk_agent.yaml"},
            {"handle": "execution", "persona": "preferences/ex07_execution_agent.yaml"},
        ],
    }


def test_provision_runs_real_cli_sequence(tmp_path) -> None:  # noqa: ANN001
    """Provisioning creates the room, one agent per persona, then seeds."""
    spec = _spec()
    calls: list[list[str]] = []

    def fake_run(args, *, capture=True):  # noqa: ANN001, ARG001
        calls.append(args)
        return _ok()

    with (
        patch.object(demo, "_fetch_persona", return_value="You are a test persona."),
        patch.object(demo, "_run", side_effect=fake_run),
        patch.object(demo, "_demo_workdir", side_effect=lambda room, handle: tmp_path / handle),
    ):
        demo._provision(spec, "claude_code", room="demo-room")

    assert ["room", "create"] in [c[:2] for c in calls]
    agent_creates = [c for c in calls if c[:2] == ["agent", "create"]]
    assert len(agent_creates) == len(spec["agents"])
    for c in agent_creates:
        assert "--adapter" in c and "claude_code" in c
    invokes = [c for c in calls if c[:2] == ["agent", "invoke"]]
    assert len(invokes) == 1
    seed_text = invokes[0][3]
    for a in spec["agents"]:
        assert f"@{a['handle']}" in seed_text


# ── cold-spawn (claude_code / cursor) plumbing ──────────────────────────────────


def test_provision_cold_spawn_subscribes_daemon_and_passes_cwd(tmp_path) -> None:  # noqa: ANN001
    """claude_code: daemon must be subscribed to the room, and every agent needs a --cwd."""
    spec = _spec()
    calls: list[list[str]] = []

    with (
        patch.object(demo, "_fetch_persona", return_value="persona"),
        patch.object(demo, "_run", side_effect=lambda args, **_: calls.append(args) or _ok()),
        patch.object(demo, "_demo_workdir", side_effect=lambda room, handle: tmp_path / handle),
    ):
        demo._provision(spec, "claude_code", room="r")

    # the daemon is subscribed to the room *before* agents are seeded
    subs = [c for c in calls if c[:2] == ["daemon", "subscribe"]]
    assert subs == [["daemon", "subscribe", "r"]]
    creates = [c for c in calls if c[:2] == ["agent", "create"]]
    assert len(creates) == len(spec["agents"])
    for c in creates:
        assert "--cwd" in c
        cwd = c[c.index("--cwd") + 1]
        assert cwd.endswith(tuple(a["handle"] for a in spec["agents"]))


def test_provision_cold_spawn_aborts_if_daemon_subscribe_fails(tmp_path) -> None:  # noqa: ANN001
    """A failed daemon subscribe is fatal — agents would never wake."""
    spec = _spec()

    def fake_run(args, *, capture=True):  # noqa: ANN001, ARG001
        if args[:2] == ["daemon", "subscribe"]:
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="no daemon")
        return _ok()

    with (
        patch.object(demo, "_fetch_persona", return_value="persona"),
        patch.object(demo, "_run", side_effect=fake_run),
        patch.object(demo, "_demo_workdir", return_value=tmp_path),
        pytest.raises(typer.Exit),
    ):
        demo._provision(spec, "claude_code", room="r")


def test_drive_consensus_summons_aligner_after_positions() -> None:
    """Once every agent has posted, the demo posts @aligner to trigger convergence."""
    cfg = type("C", (), {"server": type("S", (), {"api_url": "http://x"})()})()
    calls: list[list[str]] = []

    with (
        # all three agents have already spoken → no waiting
        patch.object(demo, "_room_senders", return_value={"growth", "risk", "execution"}),
        patch.object(demo, "_run", side_effect=lambda args, **_: calls.append(args) or _ok()),
        patch.object(demo.time, "sleep"),  # skip the settle window
    ):
        demo._drive_consensus(cfg, "demo-room", ["growth", "risk", "execution"])

    sends = [c for c in calls if c[:2] == ["room", "send"]]
    assert len(sends) == 1
    assert f"@{demo.ALIGNER_HANDLE}" in sends[0][2]
    assert "--room" in sends[0] and "demo-room" in sends[0]


def test_check_prereqs_flags_missing_daemon_for_cold_spawn() -> None:
    """claude_code with no daemon running surfaces a blocking problem with the fix."""

    class FakeCfg:
        adapters = {"claude-code": {}}
        llm = type("L", (), {"model": "anthropic/x"})()
        server = type("S", (), {"api_url": "http://localhost:8000"})()

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

    with (
        patch("mycelium.config.MyceliumConfig.load", return_value=FakeCfg()),
        patch("httpx.get", return_value=FakeResp()),
        patch.object(demo, "_daemon_running", return_value=False),
    ):
        _cfg, problems = demo._check_prereqs("claude_code")

    assert any("daemon isn't running" in p for p in problems)


def test_provision_aborts_on_persona_fetch_failure() -> None:
    spec = _spec()
    with (
        patch.object(demo, "_fetch_persona", side_effect=RuntimeError("offline")),
        patch.object(demo, "_run") as run,
        pytest.raises(typer.Exit),
    ):
        demo._provision(spec, "cursor", room="r")
    run.assert_not_called()  # nothing created if personas can't be fetched
