# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""How ``room watch --all``'s live view reads the room's stream: each thread's
messages labeled with its task, the board's notices, and the conductor said in
a few words."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mycelium import live_view
from mycelium.live_view import LiveView, describe_line


def _frame(sender: str, *, text: str = "", episode: str | None = None, payload=None) -> dict:
    content: dict[str, Any] = {"l9": {"payload": payload or {"type": "reply", "data": {}}}}
    if text:
        content["content"] = text
    return {
        "message_type": "l9_exchange",
        "sender_handle": sender,
        "episode": episode,
        "content": json.dumps(content),
    }


def _notice(**data: str) -> dict:
    return _frame("system", payload={"type": "notice", "data": data})


def test_the_view_shows_the_conversation_across_the_task_and_its_children():
    view = LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix the tests")

    turn = {
        "event": "turn",
        "protocol": "concord",
        "step": "propose",
        "to": "agent-1",
        "turn": 1,
        "cap": 4,
    }
    step = view.render(
        _frame(
            "conductor",
            text="concord · propose · turn 1 of 4 · agent-1\n\nThe room is…",
            episode="ep-root",
            payload={"type": "message", "data": {"conductor": turn}},
        )
    )
    assert step is not None
    # Drawn from the post's line, not its prose: the prompt stays out of view.
    assert "propose → agent-1 · turn 1 of 4" in step
    assert "The room is" not in step
    said = view.render(_frame("agent-1", text="Here. I'll take the repro.", episode="ep-root"))
    assert said is not None
    assert "agent-1" in said and "Fix the tests" in said and "I'll take the repro." in said

    filed = view.render(
        _notice(
            subkind="filed",
            key="work/repro",
            title="Reproduce it",
            by="agent-1",
            episode="ep-child",
            **{"for": "agent-2"},
        )
    )
    assert filed is not None
    assert "filed" in filed and "Reproduce it" in filed and "agent-2" in filed
    child = view.render(_frame("agent-2", text="Seed 4412 fails.", episode="ep-child"))
    assert child is not None and "Reproduce it" in child

    claimed = view.render(
        _notice(subkind="claimed", key="work/repro", title="Reproduce it", by="agent-2")
    )
    assert claimed is not None and "took" in claimed


def test_the_view_hides_pings_and_ends_when_the_task_resolves():
    view = LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    assert view.render(_frame("agent-1", payload={"type": "ping", "data": {}})) is None
    assert view.render({"message_type": "coordination_join", "content": "{}"}) is None
    assert view.render(_notice(subkind="resolved", key="work/repro", title="Repro")) is not None
    assert not view.done.is_set()
    assert view.render(_notice(subkind="resolved", key="work/fix", title="Fix")) is not None
    assert view.done.is_set()


def test_what_an_agent_writes_is_never_read_as_markup():
    from rich.console import Console

    view = LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix [it]")
    line = view.render(
        _frame(
            "agent-1", text="Fill in [Agent-2: build command] and [/bold] here", episode="ep-root"
        )
    )
    assert line is not None
    out = Console(width=200, record=True)
    out.print(line)
    printed = out.export_text()
    assert "[Agent-2: build command]" in printed
    assert "[/bold]" in printed
    assert "Fix [it]" in printed


def test_a_long_message_is_cut_short_with_where_to_read_the_rest():
    view = LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    view.render(
        _notice(subkind="filed", key="work/draft", title="Draft", by="agent-1", episode="ep-d")
    )
    long = "\n".join(f"line {i}" for i in range(1, 11))
    line = view.render(_frame("agent-1", text=long, episode="ep-d"))
    assert line is not None
    assert "line 6" in line and "line 7" not in line
    assert "4 more lines · board messages work/draft" in line


def test_the_last_word_in_the_task_is_kept():
    view = LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    view.render(_frame("agent-2", text="a child's message", episode="ep-child"))
    view.render(_frame("agent-1", text="# The result\n\nAll of it.", episode="ep-root"))
    assert view.last_root == ("agent-1", "# The result\n\nAll of it.")


def test_the_view_knows_how_long_the_room_has_been_quiet(monkeypatch: pytest.MonkeyPatch):
    clock = [1000.0]
    monkeypatch.setattr(live_view.time, "monotonic", lambda: clock[0])
    view = LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    clock[0] += 200
    assert view.quiet_for() == 200
    # A ping is not something the view shows, so it does not count as movement.
    view.render(_frame("agent-1", payload={"type": "ping", "data": {}}))
    assert view.quiet_for() == 200
    view.render(_frame("agent-1", text="Still on it.", episode="ep-root"))
    assert view.quiet_for() == 0


def test_each_conductor_line_is_said_in_a_few_words():
    assert (
        describe_line(
            {
                "event": "open",
                "protocol": "concord",
                "roles": {"lead": "agent-1"},
                "members": ["agent-2", "agent-3"],
                "steps": [],
            }
        )
        == "Running concord · agent-1 as lead · agent-2, agent-3"
    )
    assert (
        describe_line(
            {"event": "edge", "step": "review", "who": "sec", "stance": "reject", "next": "propose"}
        )
        == "review: sec blocked, on to propose"
    )
    close = {"event": "close", "protocol": "accord", "outcome": "resolved", "reason": ""}
    assert describe_line(close | {"steps": 2}) == "accord done · 2 steps"
    # An agreement is a success, and says what it went with.
    close = {"event": "close", "protocol": "concord", "outcome": "converged", "steps": 4}
    assert describe_line(close | {"pick": "C", "text": "15% off"}) == (
        "Everyone's on board: going with C"
    )
    assert describe_line(close | {"outcome": "rejected", "pick": "B"}) == (
        "Couldn't get everyone there · best was B"
    )
    pick = {
        "outcome": "infeasible",
        "pick": "B",
        "threshold": 70,
        "ratings": {"success": 55, "finance": 90},
        "missing": ["legal"],
    }
    assert (
        describe_line({"event": "select", "step": "pick", "select": pick})
        == "pick: B, @success at 55; no rating from @legal"
    )
