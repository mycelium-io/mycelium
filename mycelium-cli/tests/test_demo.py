# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the live ``mycelium demo`` orchestration (issues #374 / #315).

The demo is glue over the real CLI: it fetches personas, creates a room and
agents, and seeds a negotiation. These tests exercise the registry, the
prereq/argument gating, and the provisioning sequence with the subprocess and
network calls mocked — no real backend, adapter, or LLM is touched.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import demo
from mycelium.commands._demo_scenarios import (
    DEFAULT_SCENARIO,
    SCENARIOS,
    list_scenarios,
)

runner = CliRunner()


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


# ── registry ──────────────────────────────────────────────────────────────────


def test_default_scenario_first() -> None:
    assert DEFAULT_SCENARIO in SCENARIOS
    assert list_scenarios()[0]["id"] == DEFAULT_SCENARIO


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_scenario_schema(scenario_id: str) -> None:
    s = SCENARIOS[scenario_id]
    assert s["id"] == scenario_id
    for field in ("title", "tagline", "room", "task", "agents"):
        assert s[field], f"{scenario_id} missing {field}"
    handles = {a["handle"] for a in s["agents"]}
    assert len(handles) == len(s["agents"]), "duplicate handles"
    for a in s["agents"]:
        # Every agent points at a persona file in the public dataset.
        assert a["persona"].startswith("preferences/")
        assert a["persona"].endswith(".yaml")


# ── argument / prereq gating ────────────────────────────────────────────────────


def test_list_command() -> None:
    result = runner.invoke(app, ["demo", "--list"])
    assert result.exit_code == 0
    assert DEFAULT_SCENARIO in result.stdout


def test_adapter_required() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 1
    assert "--adapter is required" in result.stdout


def test_unknown_adapter_rejected() -> None:
    result = runner.invoke(app, ["demo", "--adapter", "nope"])
    assert result.exit_code == 1
    assert "Unknown adapter" in result.stdout


def test_unknown_scenario_rejected() -> None:
    result = runner.invoke(app, ["demo", "--adapter", "openclaw", "--scenario", "nope"])
    assert result.exit_code == 1
    assert "Unknown scenario" in result.stdout


def test_blocks_when_prereqs_missing() -> None:
    """Missing adapter/LLM/backend should fail fast with fixes, not provision."""
    with (
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


def test_provision_runs_real_cli_sequence() -> None:
    """Provisioning creates the room, one agent per persona, then seeds."""
    scenario = SCENARIOS[DEFAULT_SCENARIO]
    calls: list[list[str]] = []

    def fake_run(args, *, capture=True):  # noqa: ANN001, ARG001
        calls.append(args)
        return _ok()

    with (
        patch.object(demo, "_fetch_persona", return_value="You are a test persona."),
        patch.object(demo, "_run", side_effect=fake_run),
    ):
        demo._provision(scenario, "openclaw", model="m/x", room="demo-room")

    verbs = [c[:2] for c in calls]
    assert ["room", "create"] in verbs
    # one agent create per persona
    agent_creates = [c for c in calls if c[:2] == ["agent", "create"]]
    assert len(agent_creates) == len(scenario["agents"])
    for c in agent_creates:
        assert "--adapter" in c and "openclaw" in c
        assert "--model" in c  # openclaw + model provided
    # seed via agent invoke, mentioning all handles
    invokes = [c for c in calls if c[:2] == ["agent", "invoke"]]
    assert len(invokes) == 1
    seed_text = invokes[0][3]
    for a in scenario["agents"]:
        assert f"@{a['handle']}" in seed_text


def test_provision_no_model_for_non_openclaw() -> None:
    scenario = SCENARIOS[DEFAULT_SCENARIO]
    calls: list[list[str]] = []

    def fake_run(args, *, capture=True):  # noqa: ANN001, ARG001
        calls.append(args)
        return _ok()

    with (
        patch.object(demo, "_fetch_persona", return_value="persona"),
        patch.object(demo, "_run", side_effect=fake_run),
    ):
        demo._provision(scenario, "cursor", model="m/x", room="r")

    for c in [c for c in calls if c[:2] == ["agent", "create"]]:
        assert "--model" not in c  # model only applied to openclaw


def test_provision_aborts_on_persona_fetch_failure() -> None:
    scenario = SCENARIOS[DEFAULT_SCENARIO]
    with (
        patch.object(demo, "_fetch_persona", side_effect=RuntimeError("offline")),
        patch.object(demo, "_run") as run,
        pytest.raises(typer.Exit),
    ):
        demo._provision(scenario, "openclaw", model=None, room="r")
    run.assert_not_called()  # nothing created if personas can't be fetched
