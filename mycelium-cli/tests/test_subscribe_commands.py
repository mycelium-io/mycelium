# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium subscribe``.

Node-free: subscriptions live on the hub, so ``_call`` (the one place a command
reaches it) is stubbed, and each test reads what the command sent and printed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from mycelium.commands import subscribe as subscribe_cmd

runner = CliRunner()

SUB: dict[str, Any] = {
    "id": "a1b2c3d4",
    "handle": "coordinator",
    "kind": "task",
    "target": "work/release-3-1",
    "parts": True,
    "task": None,
    "created_at": "2026-10-18T12:00:00Z",
    "until": None,
    "describe": "work/release-3-1 and its parts",
}


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:
    """Every test runs under the temp ``~/.mycelium``."""


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def fake(fn, **kwargs):
        seen.append({"fn": fn.__module__.rsplit(".", 1)[-1], **kwargs})
        if "list_subscriptions" in seen[-1]["fn"]:
            return {"subscriptions": [SUB], "total": 1}
        if "unsubscribe" in seen[-1]["fn"]:
            return {"removed": [SUB]}
        return SUB

    monkeypatch.setattr(subscribe_cmd, "_call", fake)
    return seen


def _run(*args: str):
    return runner.invoke(subscribe_cmd.app, [*args, "--as", "coordinator", "--room", "ops"])


def test_a_task_subscription_sends_its_parts_and_says_it_ends_with_the_task(calls) -> None:
    result = _run("task", "work/release-3-1", "--parts")
    assert result.exit_code == 0, result.output
    body = calls[0]["body"]
    assert (calls[0]["room_name"], body.handle, body.kind.value, body.target, body.parts) == (
        "ops",
        "coordinator",
        "task",
        "work/release-3-1",
        True,
    )
    assert "Subscribed @coordinator to work/release-3-1 and its parts" in result.output
    assert "ends with its task" in result.output


@pytest.mark.parametrize(
    ("args", "kind", "target", "extra"),
    [
        (
            ["notice", "upstream:merged", "--task", "work/x"],
            "notice",
            "upstream:merged",
            {"task": "work/x"},
        ),
        (["member", "@reviewer", "--for", "3d"], "member", "@reviewer", {"span": "3d"}),
        (
            ["search", "from:reviewer approved", "--for", "never"],
            "search",
            "from:reviewer approved",
            {"span": "never"},
        ),
    ],
)
def test_each_kind_sends_what_it_names(calls, args, kind, target, extra) -> None:
    result = _run(*args)
    assert result.exit_code == 0, result.output
    body = calls[0]["body"]
    assert (body.kind.value, body.target) == (kind, target)
    for field, value in extra.items():
        assert getattr(body, field) == value


def test_ls_lists_yours_and_all_lists_everyones(calls) -> None:
    result = _run("ls")
    assert result.exit_code == 0, result.output
    assert calls[0]["handle"] == "coordinator"
    assert "a1b2c3d4" in result.output
    assert "work/release-3-1 and its parts" in result.output
    _run("ls", "--all")
    assert calls[1]["handle"] is None


def test_ls_json(calls) -> None:
    result = _run("ls", "--json")
    assert json.loads(result.output)[0]["id"] == "a1b2c3d4"


def test_rm_drops_one_by_id_or_all_with_a_yes(calls) -> None:
    result = _run("rm", "a1b2c3d4")
    assert result.exit_code == 0, result.output
    assert (calls[0]["handle"], calls[0]["id"]) == ("coordinator", "a1b2c3d4")
    assert "Unsubscribed @coordinator from work/release-3-1 and its parts" in result.output
    result = _run("rm", "--all", "--yes")
    assert result.exit_code == 0, result.output
    assert calls[1]["id"] is None


def test_rm_needs_an_id_or_all_but_not_both(calls) -> None:
    assert _run("rm").exit_code == 1
    assert _run("rm", "a1b2c3d4", "--all", "--yes").exit_code == 1
    assert calls == []
