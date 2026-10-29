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
    """Missing LLM/backend should fail fast with fixes, not provision."""
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
            return_value=(object(), ["No LLM configured."]),
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


_TASK_JSON = '{"key": "work/investment-portfolio", "episode": "urn:x:t1"}'


def _fake_cli(calls: list[list[str]]):  # noqa: ANN202
    def fake_run(args, *, capture=True):  # noqa: ANN001, ARG001
        calls.append(args)
        return _ok(_TASK_JSON if args[:2] == ["board", "new"] else "")

    return fake_run


def test_provision_runs_real_cli_sequence(tmp_path) -> None:  # noqa: ANN001
    """Provisioning creates the room, one agent per persona and the conductor,
    then files the task the negotiation runs in."""
    spec = _spec()
    calls: list[list[str]] = []

    with (
        patch.object(demo, "_fetch_persona", return_value="You are a test persona."),
        patch.object(demo, "_run", side_effect=_fake_cli(calls)),
        patch.object(demo, "_demo_workdir", side_effect=lambda room, handle: tmp_path / handle),
    ):
        key = demo._provision(spec, "claude_code", room="demo-room")

    assert key == "work/investment-portfolio"
    assert [c[:2] for c in calls][0] == ["room", "create"]
    agent_creates = [c for c in calls if c[:2] == ["agent", "create"]]
    assert len(agent_creates) == len(spec["agents"])
    for c in agent_creates:
        assert "--adapter" in c and "claude_code" in c
    engines = [c for c in calls if c[:2] == ["engine", "create"]]
    assert engines == [
        ["engine", "create", "conductor", "--kind", "conductor", "--room", "demo-room"]
    ]
    filed = [c for c in calls if c[:2] == ["board", "new"]]
    assert len(filed) == 1
    assert "--json" in filed[0]


def test_provision_stops_when_the_task_cannot_be_filed(tmp_path) -> None:  # noqa: ANN001
    spec = _spec()

    def fake_run(args, *, capture=True):  # noqa: ANN001, ARG001
        if args[:2] == ["board", "new"]:
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="nope")
        return _ok()

    with (
        patch.object(demo, "_fetch_persona", return_value="persona"),
        patch.object(demo, "_run", side_effect=fake_run),
        patch.object(demo, "_demo_workdir", side_effect=lambda room, handle: tmp_path / handle),
        pytest.raises(typer.Exit),
    ):
        demo._provision(spec, "claude_code", room="r")


# ── resident (claude_code / cursor) plumbing ────────────────────────────────────


def test_provision_resident_passes_cwd_and_creates_agents(tmp_path) -> None:  # noqa: ANN001
    """claude_code: every agent is created with a --cwd; no daemon subscribe."""
    spec = _spec()
    calls: list[list[str]] = []

    with (
        patch.object(demo, "_fetch_persona", return_value="persona"),
        patch.object(demo, "_run", side_effect=_fake_cli(calls)),
        patch.object(demo, "_demo_workdir", side_effect=lambda room, handle: tmp_path / handle),
    ):
        demo._provision(spec, "claude_code", room="r")

    # No daemon subscribe in the resident model.
    assert not [c for c in calls if c[:2] == ["daemon", "subscribe"]]
    creates = [c for c in calls if c[:2] == ["agent", "create"]]
    assert len(creates) == len(spec["agents"])
    for c in creates:
        assert "--cwd" in c
        cwd = c[c.index("--cwd") + 1]
        assert cwd.endswith(tuple(a["handle"] for a in spec["agents"]))


def test_drive_consensus_runs_concord_in_the_tasks_thread() -> None:
    """The demo summons the conductor's concord flow inside the task it filed
    (a conductor run from the room, outside a task, is refused), naming every
    agent so the flow binds them."""
    calls: list[list[str]] = []

    with patch.object(demo, "_run", side_effect=lambda args, **_: calls.append(args) or _ok()):
        demo._drive_consensus(
            "demo-room", "work/portfolio", ["growth", "risk", "execution"], "investment portfolio"
        )

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:4] == ["board", "coordinate", "work/portfolio", demo.CONDUCTOR_HANDLE]
    ask = cmd[4]
    assert ask.startswith("concord @~growth @~risk @~execution: ")
    assert "investment portfolio" in ask
    assert cmd[cmd.index("--room") + 1] == "demo-room"


def test_provision_aborts_on_persona_fetch_failure() -> None:
    spec = _spec()
    with (
        patch.object(demo, "_fetch_persona", side_effect=RuntimeError("offline")),
        patch.object(demo, "_run") as run,
        pytest.raises(typer.Exit),
    ):
        demo._provision(spec, "cursor", room="r")
    run.assert_not_called()  # nothing created if personas can't be fetched
