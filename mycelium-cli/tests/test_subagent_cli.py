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
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.runner.sessions import Follower, finished_subagents, open_subagents
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
    assert "add --as builder:review to every mycelium command that posts" in out
    assert "commands that only read don't take it" in out
    assert "mycelium subagent end builder:review --room checkout" in out
    # The optional fourth line, set apart from the three.
    assert "Messages to it wake you." in out
    assert "mycelium await --as builder:review --room checkout --timeout 5" in out


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


def test_from_an_agent_s_pane_a_post_goes_out_only_as_it_or_its_subagents(
    hub: StandInHub, monkeypatch: pytest.MonkeyPatch
):
    # A subagent that never ran `subagent start` made up a handle and posted
    # with `room send`; `respond` refused that, `send` didn't ask.
    monkeypatch.setenv("MYCELIUM_AGENT_PANE", "builder")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "builder")
    hub.answer = lambda r: (
        201,
        {
            "id": "6f1c2a7e-0d3b-4c5e-9a8f-1b2c3d4e5f60",
            "room_name": "checkout",
            "sender_handle": json.loads(r.content)["sender_handle"],
            "message_type": "broadcast",
            "content": "x",
            "created_at": "2026-11-15T10:00:00+00:00",
        },
    )
    made_up = runner.invoke(app, ["room", "send", "a suggestion", "--as", "builder-helper"])
    assert made_up.exit_code != 0
    assert "subagent start" in made_up.output
    assert not hub.sent("POST", "/api/rooms/checkout/messages")

    own = runner.invoke(app, ["room", "send", "a suggestion", "--as", "builder:review"])
    assert own.exit_code == 0, own.output
    assert hub.sent("POST", "/api/rooms/checkout/messages")


def test_a_subagent_ends_itself_with_the_as_its_brief_says_to_add(hub: StandInHub):
    hub.answer = lambda _r: {**REVIEW, "state": "ended", "ended_at": "2026-11-15T10:05:00+00:00"}
    result = runner.invoke(app, ["subagent", "end", "builder:review", "--as", "builder:review"])
    assert result.exit_code == 0, result.output
    assert hub.sent("DELETE", "/api/rooms/checkout/subagents/builder:review")


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


def _done(call_id: str, name: str = "Agent") -> dict:
    return {**_call(name, "completed"), "toolCallId": call_id}


def test_finished_subagent_steps_are_counted_up_from_the_first_look(tmp_path: Path):
    # Counting reads no herdr, so it has none.
    follower = Follower(bridge=cast("Any", None), base=tmp_path)
    key = ("checkout", "builder")
    # What had finished before the first look is where the count starts.
    follower._count_finished(key, finished_subagents({"entries": [_done("a"), _done("b")]}))
    assert follower.subagents_finished[key] == 0
    # A step that opened and closed between two looks still counts, and one
    # that scrolled out of the latest entries doesn't count against it.
    follower._count_finished(key, finished_subagents({"entries": [_done("b"), _done("c")]}))
    assert follower.subagents_finished[key] == 1
    follower._count_finished(
        key, finished_subagents({"entries": [_done("c"), _done("d"), _done("x", "Bash")]})
    )
    assert follower.subagents_finished[key] == 2


def _agent_call(call_id: str, *, background: bool = False) -> dict:
    """An assistant line starting a subagent, as Claude Code writes it."""
    given: dict[str, Any] = {"description": "look", "prompt": "secret", "subagent_type": "Explore"}
    if background:
        given["run_in_background"] = True
    block = {"type": "tool_use", "id": call_id, "name": "Agent", "input": given}
    return {"type": "assistant", "message": {"id": f"m-{call_id}", "content": [block]}}


def _agent_result(call_id: str, text: str) -> dict:
    block = {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": [{"type": "text", "text": text}],
    }
    return {"type": "user", "message": {"role": "user", "content": [block]}}


def _notified(call_id: str, status: str) -> dict:
    """The message Claude Code adds when a background step ends."""
    text = (
        f"<task-notification>\n<task-id>a1</task-id>\n<tool-use-id>{call_id}</tool-use-id>\n"
        f"<status>{status}</status>\n<summary>Agent finished</summary>\n</task-notification>"
    )
    return {
        "type": "user",
        "origin": {"kind": "task-notification"},
        "message": {"role": "user", "content": text},
    }


LAUNCHED = "Async agent launched successfully.\nagentId: a1"


def _steps(*lines: dict) -> tuple[int, set[str]]:
    from mycelium.integrations.agents.claude_session import convert

    entries, _ = convert(list(lines))
    body = {"entries": entries}
    return open_subagents(body), finished_subagents(body)


def test_a_background_subagent_is_open_until_the_session_is_told_it_ended():
    """Its launch coming back isn't its end: counting it as one ended a
    subagent a minute into its work, and the hub refused all it said after.
    Lines shaped as Claude Code writes them, through the runner's converter."""
    # Launched in the background by the harness (no flag) or by the flag: open.
    assert _steps(_agent_call("bg"), _agent_result("bg", LAUNCHED)) == (1, set())
    flagged = _agent_call("bg", background=True)
    assert _steps(flagged, _agent_result("bg", "started")) == (1, set())
    # Told it ended: finished, however it ended.
    for status in ("completed", "failed", "killed"):
        told = _steps(_agent_call("bg"), _agent_result("bg", LAUNCHED), _notified("bg", status))
        assert told == (0, {"bg"})
    # Told mid-turn, as a queued command rather than a message of its own.
    queued = {
        "type": "attachment",
        "attachment": {
            "type": "queued_command",
            "commandMode": "task-notification",
            "prompt": _notified("bg", "completed")["message"]["content"],
        },
    }
    assert _steps(_agent_call("bg"), _agent_result("bg", LAUNCHED), queued) == (0, {"bg"})
    # A foreground one still ends when its result comes back.
    assert _steps(_agent_call("fg"), _agent_result("fg", "found 3 files")) == (0, {"fg"})
    # A notification for some other call ends nothing here.
    other = _steps(_agent_call("bg"), _agent_result("bg", LAUNCHED), _notified("zz", "completed"))
    assert other == (1, set())
