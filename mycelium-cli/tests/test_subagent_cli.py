# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium subagent start`` / ``end``, a subagent posting with ``--as``, and the
count of open subagent steps the runner reads from a session (never its text).

The hub is a stand-in at httpx's transport, answering with the shapes it really
sends (the typed client parses them against ``openapi.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.runner.sessions import open_subagents
from tests.conftest import StandInHub, install_stand_in_hub

runner = CliRunner()

REVIEW = {
    "handle": "builder:review",
    "parent": "builder",
    "name": "review",
    "state": "working",
    "started_at": "2026-11-15T10:00:00+00:00",
    "ended_at": None,
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "checkout")
    for name in ("MYCELIUM_API_URL", "MYCELIUM_AGENT_HANDLE", "HERDR_PANE_ID"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> StandInHub:
    return install_stand_in_hub(monkeypatch)


def test_start_records_it_as_its_parent_and_prints_the_three_lines(hub: StandInHub):
    hub.answer = lambda _r: (201, REVIEW)
    result = runner.invoke(app, ["subagent", "start", "review", "--as", "builder"])
    assert result.exit_code == 0, result.output
    (sent,) = hub.sent("POST", "/api/rooms/checkout/subagents")
    assert json.loads(sent.content) == {"name": "review", "parent": "builder"}
    out = result.output
    assert "You are @builder:review, a subagent of @builder, in the Mycelium room checkout." in out
    assert "add --as builder:review to every mycelium command" in out
    assert "mycelium subagent end builder:review --room checkout" in out


def test_start_says_the_hub_s_reason(hub: StandInHub):
    hub.answer = lambda _r: (422, {"detail": "A subagent's name is lowercase letters..."})
    result = runner.invoke(app, ["subagent", "start", "Review Bot", "--as", "builder"])
    assert result.exit_code == 1
    assert "A subagent's name is lowercase letters" in result.output


def test_end_ends_it(hub: StandInHub):
    hub.answer = lambda _r: {**REVIEW, "state": "ended", "ended_at": "2026-11-15T10:05:00+00:00"}
    result = runner.invoke(app, ["subagent", "end", "builder:review"])
    assert result.exit_code == 0, result.output
    (sent,) = hub.sent("DELETE", "/api/rooms/checkout/subagents/builder:review")
    assert sent is not None
    assert "Ended @builder:review" in result.output


def test_a_subagent_posts_as_itself_with_as(hub: StandInHub):
    hub.answer = lambda _r: {"room": "checkout", "handle": "builder:review", "message_id": "r-1"}
    result = runner.invoke(app, ["respond", "refund tests pass", "--as", "builder:review"])
    assert result.exit_code == 0, result.output
    (sent,) = hub.sent("POST", "/api/rooms/checkout/reply")
    assert json.loads(sent.content)["handle"] == "builder:review"


def _call(name: str, status: str) -> dict:
    return {"sessionUpdate": "tool_call", "name": name, "status": status, "title": "secret"}


def test_only_a_count_of_open_subagent_steps_is_read_from_a_session():
    body = {
        "entries": [
            _call("Agent", "in_progress"),
            _call("Task", "pending"),
            _call("Agent", "completed"),
            _call("Bash", "in_progress"),
            {"sessionUpdate": "agent_message", "content": "secret"},
        ]
    }
    assert open_subagents(body) == 2
    assert open_subagents({"entries": []}) == 0
