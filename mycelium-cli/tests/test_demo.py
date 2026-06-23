# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the isolated ``mycelium demo`` walkthrough (issues #374 / #315).

These guard the bundled scenario fixtures and verify the offline replay runs
end-to-end without a backend, LLM, or daemon.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import demo
from mycelium.commands._demo_scenarios import (
    DEFAULT_SCENARIO,
    SCENARIOS,
    list_scenarios,
)

runner = CliRunner()

_VALID_ACTIONS = {"propose", "counter", "accept", "reject"}
_VALID_KINDS = {"system", "seed", "join", "tick", "consensus"}


def test_default_scenario_exists() -> None:
    assert DEFAULT_SCENARIO in SCENARIOS
    assert list_scenarios()[0]["id"] == DEFAULT_SCENARIO


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_scenario_schema(scenario_id: str) -> None:
    s = SCENARIOS[scenario_id]
    assert s["id"] == scenario_id
    for field in (
        "title",
        "tagline",
        "domain",
        "model",
        "room",
        "seed",
        "agents",
        "issues",
        "steps",
        "metrics",
    ):
        assert s[field], f"{scenario_id} missing {field}"

    handles = {a["handle"] for a in s["agents"]}
    assert len(handles) == len(s["agents"]), "duplicate agent handles"

    # Exactly one consensus step, and it is last.
    consensus = [st for st in s["steps"] if st["kind"] == "consensus"]
    assert len(consensus) == 1
    assert s["steps"][-1]["kind"] == "consensus"

    for st in s["steps"]:
        assert st["kind"] in _VALID_KINDS
        if st["kind"] == "tick":
            assert st["agent"] in handles, f"tick references unknown agent {st['agent']}"
            assert st["action"] in _VALID_ACTIONS
            assert isinstance(st["round"], int)
        if st["kind"] == "join":
            assert st["agent"] in handles

    # Metrics consensus flag matches the consensus step outcome.
    assert s["metrics"]["consensus"] == consensus[0]["reached"]


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_replay_runs_offline(scenario_id: str) -> None:
    """Replay must complete with no backend and produce the consensus banner."""
    demo._replay(SCENARIOS[scenario_id], fast=True)  # should not raise


def test_demo_list_command() -> None:
    result = runner.invoke(app, ["demo", "--list"])
    assert result.exit_code == 0
    assert DEFAULT_SCENARIO in result.stdout


def test_demo_replay_command_default() -> None:
    result = runner.invoke(app, ["demo", "--fast"])
    assert result.exit_code == 0
    # Default scenario reaches consensus.
    assert "CONSENSUS" in result.stdout
    assert "reproduce it yourself" in result.stdout.lower() or "reproduce" in result.stdout.lower()


def test_demo_unknown_scenario_errors() -> None:
    result = runner.invoke(app, ["demo", "--scenario", "nope"])
    assert result.exit_code == 1
