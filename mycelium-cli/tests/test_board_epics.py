# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Epics in the terminal: drawn as the hub works them out, never re-derived."""

import json
from pathlib import Path

from rich.console import Console

from mycelium.board import epics

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "board-vocabulary.json").read_text()
)["epic"]


def part(key: str, title: str, state: str, **more) -> dict:
    return {"key": key, "title": title, "state": state, "waiting_on": [], **more}


EPIC = {
    **part("work/apple-pay", "Apple Pay for everyone", "working", holder="builder"),
    "lead": "builder",
    "done": 1,
    "total": 4,
    "steps": [["work/stripe"], ["work/double", "work/checkout"], ["work/iphone"]],
    "path": [
        part("work/stripe", "Move card payments to Stripe", "done"),
        part(
            "work/double",
            "Fix the double charges",
            "working",
            holder="builder",
            latest={"sender": "reviewer", "text": "Approved #504.", "at": None},
        ),
        part("work/checkout", "Add Apple Pay to checkout", "open"),
        part("work/iphone", "Test it on a real iPhone", "waiting", waiting_on=["work/checkout"]),
    ],
}


def plain(lines) -> str:
    console = Console(width=200, record=True, color_system=None)
    for line in lines:
        console.print(line)
    return console.export_text()


def test_states_match_the_contract():
    assert CONTRACT["part_states"] == epics.PART_STATES
    assert CONTRACT["waiting_kinds"] == epics.WAITING_KINDS
    assert set(epics.STATE_MARK) == set(epics.PART_STATES)


def test_an_epic_draws_its_parts_in_path_order_with_side_by_side_steps():
    text = plain(epics.epic_lines(EPIC))
    assert "1 of 4 parts are done. @builder leads it." in text
    # Each part is two lines: its step, mark and title, then where it stands.
    lines = [ln.strip() for ln in text.splitlines()[1:]]
    assert lines[0] == "1 ✓ Move card payments to Stripe"
    assert lines[1] == "Done  work/stripe"
    assert lines[2] == "2 ● Fix the double charges"
    assert lines[4] == "2 ○ Add Apple Pay to checkout"
    assert lines[7] == "Waits on Add Apple Pay to checkout  work/iphone"
    # The latest line shows only where it's asked for.
    assert "Approved #504." not in text
    assert "@reviewer: Approved #504." in plain(epics.epic_lines(EPIC, latest=True))


def test_where_a_part_stands_is_a_sentence():
    assert epics.where_it_stands(part("k", "t", "open")) == "Nobody has it yet"
    assert epics.where_it_stands(part("k", "t", "working", holder="ana")) == "@ana is on it"
    assert epics.where_it_stands(part("k", "t", "blocked", blocked_by="CI")) == "Blocked: CI"


def test_the_list_beside_the_tree_leaves_out_what_the_tree_drew():
    assert epics.epic_parts({"epics": [EPIC], "tasks": []}) == {
        "work/apple-pay",
        "work/stripe",
        "work/double",
        "work/checkout",
        "work/iphone",
    }
    assert epics.epic_parts(None) == set()


def test_a_waiting_item_says_who_asked_where_and_which_epic():
    line = plain(
        [
            epics.waiting_line(
                {
                    "kind": "ask",
                    "key": "work/double",
                    "title": "Fix the double charges",
                    "epic_title": "Apple Pay for everyone",
                    "sender": "builder",
                    "text": "Refund automatically, or send to support first?",
                    "count": 2,
                }
            )
        ]
    )
    assert '@builder asked you in "Fix the double charges" (2 messages).' in line
    assert 'It\'s part of "Apple Pay for everyone".' in line
    assert "Refund automatically" in line
