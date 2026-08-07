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
            return_value=(object(), ["Adapter 'openclaw' is not installed."]),
        ),
        patch.object(demo, "_provision") as prov,
    ):
        result = runner.invoke(app, ["demo", "--adapter", "openclaw", "--yes"])
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


def test_provision_runs_real_cli_sequence() -> None:
    """Provisioning creates the room, one agent per persona, then seeds."""
    spec = _spec()
    calls: list[list[str]] = []

    def fake_run(args, *, capture=True):  # noqa: ANN001, ARG001
        calls.append(args)
        return _ok()

    with (
        patch.object(demo, "_fetch_persona", return_value="You are a test persona."),
        patch.object(demo, "_run", side_effect=fake_run),
        patch.object(demo, "_await_openclaw_ready") as ready,
        patch.object(demo, "_discover_openclaw_auth_source", return_value="main"),
    ):
        demo._provision(spec, "openclaw", model="m/x", room="demo-room")

    assert ["room", "create"] in [c[:2] for c in calls]
    agent_creates = [c for c in calls if c[:2] == ["agent", "create"]]
    assert len(agent_creates) == len(spec["agents"])
    for c in agent_creates:
        assert "--adapter" in c and "openclaw" in c
        assert "--model" in c  # openclaw + model provided
        # discovered auth source must be copied so the agent can authenticate
        assert "--copy-auth-from" in c and "main" in c
    invokes = [c for c in calls if c[:2] == ["agent", "invoke"]]
    assert len(invokes) == 1
    seed_text = invokes[0][3]
    for a in spec["agents"]:
        assert f"@{a['handle']}" in seed_text
    # openclaw: must wait for the gateway to re-subscribe before seeding
    ready.assert_called_once()


def test_provision_explicit_auth_from_overrides_discovery() -> None:
    """--auth-from wins over auto-discovery and is passed to every create."""
    spec = _spec()
    calls: list[list[str]] = []

    with (
        patch.object(demo, "_fetch_persona", return_value="p"),
        patch.object(demo, "_run", side_effect=lambda args, **_: calls.append(args) or _ok()),
        patch.object(demo, "_await_openclaw_ready"),
        patch.object(demo, "_discover_openclaw_auth_source", return_value="auto") as disc,
    ):
        demo._provision(spec, "openclaw", model=None, room="r", auth_from="julia-agent")

    disc.assert_not_called()  # explicit source short-circuits discovery
    for c in [c for c in calls if c[:2] == ["agent", "create"]]:
        assert c[c.index("--copy-auth-from") + 1] == "julia-agent"


def test_provision_warns_when_no_auth_source(capsys: pytest.CaptureFixture[str]) -> None:
    """No authenticated agent to copy from → warn, and don't pass the flag."""
    spec = _spec()
    calls: list[list[str]] = []

    with (
        patch.object(demo, "_fetch_persona", return_value="p"),
        patch.object(demo, "_run", side_effect=lambda args, **_: calls.append(args) or _ok()),
        patch.object(demo, "_await_openclaw_ready"),
        patch.object(demo, "_discover_openclaw_auth_source", return_value=None),
    ):
        demo._provision(spec, "openclaw", model=None, room="r")

    assert "No authenticated OpenClaw agent" in capsys.readouterr().out
    for c in [c for c in calls if c[:2] == ["agent", "create"]]:
        assert "--copy-auth-from" not in c  # nothing to copy → flag omitted


def test_provision_no_model_for_non_openclaw(tmp_path) -> None:  # noqa: ANN001
    spec = _spec()
    calls: list[list[str]] = []

    def fake_run(args, *, capture=True):  # noqa: ANN001, ARG001
        calls.append(args)
        return _ok()

    with (
        patch.object(demo, "_fetch_persona", return_value="persona"),
        patch.object(demo, "_run", side_effect=fake_run),
        patch.object(demo, "_demo_workdir", return_value=tmp_path),
    ):
        demo._provision(spec, "cursor", model="m/x", room="r")

    for c in [c for c in calls if c[:2] == ["agent", "create"]]:
        assert "--model" not in c  # model only applied to openclaw


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
        demo._provision(spec, "claude_code", model=None, room="r")

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
        demo._provision(spec, "claude_code", model=None, room="r")


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
        demo._provision(spec, "openclaw", model=None, room="r")
    run.assert_not_called()  # nothing created if personas can't be fetched


# --------------------------------------------------------------------------- #
# _await_openclaw_ready — the seed must wait for SSE re-subscription
# --------------------------------------------------------------------------- #


def _write_auth(agents_dir, name, profiles) -> None:
    d = agents_dir / name / "agent"
    d.mkdir(parents=True)
    (d / "auth-profiles.json").write_text(__import__("json").dumps({"profiles": profiles}))


def test_discover_auth_prefers_anthropic_and_skips_empty(tmp_path) -> None:
    agents = tmp_path / ".openclaw" / "agents"
    agents.mkdir(parents=True)
    _write_auth(agents, "empty", {})  # empty profiles — skipped
    _write_auth(agents, "openai-only", {"openai-codex:default": {"type": "oauth"}})
    _write_auth(agents, "good", {"anthropic:claude": {"type": "token"}})
    with patch.object(demo.Path, "home", return_value=tmp_path):
        # exclude the demo agents themselves; anthropic source is preferred
        assert demo._discover_openclaw_auth_source(exclude=set()) == "good"


def test_discover_auth_falls_back_to_any_nonempty(tmp_path) -> None:
    agents = tmp_path / ".openclaw" / "agents"
    agents.mkdir(parents=True)
    _write_auth(agents, "empty", {})
    _write_auth(agents, "oauthy", {"openai-codex:default": {"type": "oauth"}})
    with patch.object(demo.Path, "home", return_value=tmp_path):
        assert demo._discover_openclaw_auth_source(exclude=set()) == "oauthy"


def test_discover_auth_excludes_and_returns_none(tmp_path) -> None:
    agents = tmp_path / ".openclaw" / "agents"
    agents.mkdir(parents=True)
    _write_auth(agents, "growth", {"anthropic:claude": {"type": "token"}})  # a demo agent
    with patch.object(demo.Path, "home", return_value=tmp_path):
        # the only authed agent is one we're creating → nothing to copy from
        assert demo._discover_openclaw_auth_source(exclude={"growth"}) is None


def test_await_ready_noop_when_openclaw_absent() -> None:
    """No openclaw on PATH → nothing to wait for; never shells out or sleeps."""
    with (
        patch.object(demo.shutil, "which", return_value=None),
        patch.object(demo.subprocess, "run") as run,
        patch.object(demo.time, "sleep") as sleep,
    ):
        demo._await_openclaw_ready()
    run.assert_not_called()
    sleep.assert_not_called()


def test_await_ready_settles_once_gateway_running() -> None:
    """Gateway reports running → settle once for the SSE subscription, then return."""
    with (
        patch.object(demo.shutil, "which", return_value="/usr/bin/openclaw"),
        patch.object(demo.subprocess, "run", return_value=_ok("Runtime: running (pid 1)")),
        patch.object(demo.time, "sleep") as sleep,
    ):
        demo._await_openclaw_ready(settle=4.0)
    # the only sleep is the settle (no poll-retry sleeps, since it's ready first try)
    sleep.assert_called_once_with(4.0)


def test_await_ready_times_out_and_warns(capsys: pytest.CaptureFixture[str]) -> None:
    """Gateway never reports running → bounded wait ends with a warning, no hang."""
    not_running = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="down")
    # monotonic: start (0), then jump past the deadline so the loop exits after one poll.
    with (
        patch.object(demo.shutil, "which", return_value="/usr/bin/openclaw"),
        patch.object(demo.subprocess, "run", return_value=not_running),
        patch.object(demo.time, "sleep"),
        patch.object(demo.time, "monotonic", side_effect=[0.0, 0.5, 999.0]),
    ):
        demo._await_openclaw_ready(timeout=30.0)
    assert "didn't report ready" in capsys.readouterr().out
