# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium schedule``.

Node-free: schedules live on the hub, so ``_call`` (the one place a command
reaches it) is stubbed, and each test reads what the command sent and printed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from mycelium.commands import schedule as schedule_cmd

runner = CliRunner()

SCHEDULE: dict[str, Any] = {
    "name": "board-check",
    "owner": "builder",
    "every": "17m",
    "cron": None,
    "prompt": "look at the board",
    "check": "stale",
    "task": None,
    "state": "active",
    "paused": False,
    "created_by": "julia",
    "created_at": "2026-10-08T12:00:00Z",
    "updated_at": "2026-10-08T12:00:00Z",
    "expires_at": "2099-10-15T12:00:00Z",
    "next_run": "2099-10-08T12:17:00Z",
    "last_run": "2026-10-08T12:00:00Z",
    "last_result": "quiet",
    "runs": 4,
    "wakes": 1,
    "quiet": 3,
    "history": [
        {"at": "2026-10-08T12:51:00Z", "result": "quiet", "trigger": "schedule", "missed": 0},
        {"at": "2026-10-08T12:34:00Z", "result": "quiet", "trigger": "schedule", "missed": 0},
        {
            "at": "2026-10-08T12:17:00Z",
            "result": "woke",
            "trigger": "schedule",
            "missed": 2,
            "found": ['work/checkout "Ship it": your lease is stale'],
            "found_total": 1,
        },
        {"at": "2026-10-08T12:00:00Z", "result": "quiet", "trigger": "manual", "missed": 0},
    ],
}


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:
    """Every test runs under the temp ``~/.mycelium``."""


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def fake(fn, **kwargs):
        seen.append({"fn": fn.__module__.rsplit(".", 1)[-1], **kwargs})
        if "list_schedules" in seen[-1]["fn"]:
            return {"schedules": [SCHEDULE], "total": 1, "checks": {}}
        if "run_schedule" in seen[-1]["fn"]:
            return {
                "at": "2026-10-08T12:00:00Z",
                "result": "woke",
                "trigger": "manual",
                "found": ["@julia: are we shipping?"],
            }
        if "delete_schedule" in seen[-1]["fn"]:
            return None
        return SCHEDULE

    monkeypatch.setattr(schedule_cmd, "_call", fake)
    return seen


def test_add_sends_the_owner_timing_and_check(calls) -> None:
    result = runner.invoke(
        schedule_cmd.app,
        [
            "add",
            "board-check",
            "look at the board",
            "--every",
            "17m",
            "--check",
            "stale",
            "--for",
            "@builder",
            "--as",
            "julia",
            "--room",
            "ops",
        ],
    )
    assert result.exit_code == 0, result.output
    body = calls[0]["body"]
    assert (calls[0]["room_name"], body.owner, body.every, body.check) == (
        "ops",
        "builder",
        "17m",
        "stale",
    )
    assert "Scheduled board-check for @builder" in result.output


def test_add_wakes_whoever_is_acting_by_default(calls) -> None:
    result = runner.invoke(
        schedule_cmd.app,
        [
            "add",
            "board-check",
            "--body",
            "look",
            "--cron",
            "0 9 * * 1-5",
            "--as",
            "reviewer",
            "--room",
            "ops",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["body"].owner == "reviewer"
    assert calls[0]["body"].cron == "0 9 * * 1-5"


def test_ls_shows_what_each_schedule_has_cost(calls) -> None:
    result = runner.invoke(schedule_cmd.app, ["ls", "--room", "ops"], env={"COLUMNS": "160"})
    assert result.exit_code == 0, result.output
    assert "board-check" in result.output
    assert "@builder" in result.output
    assert "1 model turn(s) spent on schedules in ops" in result.output


def test_ls_json_is_the_list(calls) -> None:
    result = runner.invoke(schedule_cmd.app, ["ls", "--room", "ops", "--json"])
    assert json.loads(result.output)[0]["name"] == "board-check"


def test_show_folds_quiet_runs_together(calls) -> None:
    result = runner.invoke(schedule_cmd.app, ["show", "board-check", "--room", "ops"])
    assert result.exit_code == 0, result.output
    assert "… 2 quiet run(s)" in result.output
    assert "… 1 quiet run(s)" in result.output
    assert "+2 missed" in result.output
    assert "your lease is stale" in result.output


def test_pause_resume_and_renew_patch_only_what_they_change(calls) -> None:
    runner.invoke(schedule_cmd.app, ["pause", "board-check", "--room", "ops"])
    runner.invoke(schedule_cmd.app, ["resume", "board-check", "--room", "ops"])
    runner.invoke(schedule_cmd.app, ["renew", "board-check", "--days", "3", "--room", "ops"])
    bodies = [c["body"].to_dict() for c in calls]
    assert bodies[0]["paused"] is True
    assert bodies[1]["paused"] is False
    assert (bodies[2]["renew"], bodies[2]["renew_days"]) == (True, 3.0)
    assert "every" not in bodies[0]


def test_run_says_what_the_check_found(calls) -> None:
    result = runner.invoke(schedule_cmd.app, ["run", "board-check", "--wake", "--room", "ops"])
    assert result.exit_code == 0, result.output
    assert calls[0]["body"].wake is True
    assert "woke" in result.output
    assert "are we shipping?" in result.output


def test_rm_asks_first(calls) -> None:
    result = runner.invoke(schedule_cmd.app, ["rm", "board-check", "--room", "ops"], input="n\n")
    assert result.exit_code == 0
    assert calls == []
    result = runner.invoke(schedule_cmd.app, ["rm", "board-check", "--room", "ops", "--yes"])
    assert "Deleted board-check" in result.output


def test_a_refusal_says_the_hubs_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 422
        content = b'{"detail": "every 1m is more often than the hub\'s minimum, 5m"}'

    class _Client:
        def __enter__(self):
            return object()

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(schedule_cmd, "typed_client", lambda: _Client())
    with pytest.raises(typer.Exit):
        schedule_cmd._call(lambda **_k: _Resp())
