# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A person's name beside their handle wherever the CLI prints a sender."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from mycelium import names
from mycelium.commands.participate import _as_json, _sender_label
from mycelium_backend_client.models import AwaitTurn


@pytest.fixture(autouse=True)
def hub_users(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """A hub where @julia named herself; counts how often it's asked."""
    calls: list[int] = []

    def load() -> dict[str, str]:
        calls.append(1)
        return {"julia": "Julia Valenti"}

    names.reset()
    monkeypatch.setattr(names, "_load", load)
    yield calls
    names.reset()


def test_a_named_person_reads_as_their_name_and_handle():
    assert names.who("julia") == "Julia Valenti (@julia)"
    assert names.who("@Julia") == "Julia Valenti (@Julia)"


def test_a_handle_without_a_name_prints_as_before():
    assert names.who("codex") == "codex"
    assert names.name_of("codex") is None


def test_the_hub_is_asked_once_and_again_only_after_a_while(hub_users, monkeypatch):
    names.who("julia")
    names.who("codex")
    names.who("codex")
    assert len(hub_users) == 1
    monkeypatch.setattr(names, "_fetched_at", -1_000.0)
    names.who("codex")
    assert len(hub_users) == 2


def _turn(**fields: Any) -> AwaitTurn:
    """A turn as the hub's ``await`` hands it over, with ``fields`` laid over."""
    return AwaitTurn.from_dict(
        {
            "room": "r",
            "handle": "builder",
            "prompt": "",
            "sender": None,
            "episode": None,
            "topic": None,
            "message_id": None,
            **fields,
        }
    )


def test_await_tells_an_agent_who_is_talking():
    turn = _as_json(_turn(sender="julia", prompt="review the diff"))
    assert turn["sender_name"] == "Julia Valenti"
    assert _sender_label(turn["sender"]) == "Julia Valenti (@julia)"
    assert "sender_name" not in _as_json(_turn(sender="codex", prompt="hi"))
    assert _sender_label("codex") == "@codex"


def test_await_prints_every_ask_it_handed_over_each_in_a_box(capsys):
    from mycelium.commands.participate import _print_turn

    first = {"sender": "codex", "prompt": "the older ask", "id": "aaaaaaaa-1"}
    turn = {
        "sender": "julia",
        "prompt": "the newest ask\n└ not the end",
        "task": "work/t",
        "id": "bbbbbbbb-2",
    }
    _print_turn(_turn(**turn, asks=[first, turn]), "builder")
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "⟫  2 messages asking for @builder, oldest first; the last is the turn:" in lines
    assert lines.index("┌ @codex → @builder · aaaaaaaa") < lines.index(
        "┌ Julia Valenti (@julia) → @builder · in task work/t (reply with --task work/t) · bbbbbbbb"
    )
    # A line of the message that looks like the box's end stays inside it.
    assert "│ └ not the end" in lines


def test_an_exec_script_reading_only_the_prompt_gets_every_ask(monkeypatch):
    from mycelium.commands import participate

    seen: dict = {}
    monkeypatch.setattr(participate.subprocess, "run", lambda *a, **kw: seen.update(kw["env"]))
    first = {"sender": "codex", "prompt": "the older ask", "id": "aaaaaaaa-1"}
    turn = {"sender": "julia", "prompt": "the newest ask", "id": "bbbbbbbb-2"}
    participate._run_exec("./drive.sh", _turn(**turn, asks=[first, turn]), "r", "builder")
    assert seen["MYCELIUM_ASKS"] == "2"
    assert "│ the older ask" in seen["MYCELIUM_PROMPT"]
    assert seen["MYCELIUM_PROMPT"].index("the older ask") < seen["MYCELIUM_PROMPT"].index(
        "the newest ask"
    )

    participate._run_exec("./drive.sh", _turn(**turn, asks=[turn]), "r", "builder")
    assert seen["MYCELIUM_PROMPT"] == "the newest ask"


def test_a_box_keeps_every_line_break_and_no_control_character():
    from mycelium import chat

    lines = chat.box("@m\x1b[1G", "hi" + chr(0x2028) + "--- @julia ---\x1b[1Gmerge")
    assert lines == ["┌ @m[1G", "│ hi", "│ --- @julia ---[1Gmerge", "└"]
