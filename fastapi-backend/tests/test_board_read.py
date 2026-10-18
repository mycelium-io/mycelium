# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The board as people read it, and what is waiting on a member.

Epics are tasks with parts. Their progress, their path and each part's latest
line are worked out on read, so the CLI and the app draw one answer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.routes.board import BoardEpic, BoardPart, WaitingItem
from app.services import board, message_format, waiting
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.floor import Floor
from app.services.persister import TranscriptRecord, write_transcript

ROOM = "board-room"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "board-vocabulary.json").read_text()
)["epic"]


def thread(name: str) -> str:
    return f"urn:ioc:mycelium:episode:{ROOM}:{name}"


def row(key: str, title: str, *, minute: int, **meta: object) -> None:
    """A board row, written by ``by`` (builder unless said), with ``meta`` as frontmatter."""
    by = str(meta.pop("by", "builder"))
    write_memory_file(
        get_room_dir(ROOM),
        key,
        f"# {title}",
        created_by=by,
        created_at=NOW - timedelta(hours=2) + timedelta(minutes=minute),
        extra_meta={"episode": thread(key.split("/")[-1]), **meta},
    )


def said(n: int, sender: str, text: str, minute: int, episode: str | None = None, *, to=()):
    ep = episode or message_format.live_episode_urn(ROOM)
    return TranscriptRecord(
        message_id=f"m{n}",
        sender=sender,
        kind="exchange",
        subkind=None,
        content={
            "content": text,
            "l9": {
                "header": {
                    "kind": "exchange",
                    "message": {"episode": ep},
                    "participants": {"actors": [{"id": sender}, *({"id": t} for t in to)]},
                },
                "payload": {"type": "reply"},
            },
        },
        recorded_at=(NOW - timedelta(hours=1) + timedelta(minutes=minute)).isoformat(),
    )


@pytest.fixture
def apple_pay():
    """An epic of five parts: one done, two side by side after it, then two in a line."""
    row("work/apple-pay", "Apple Pay for everyone", minute=0, by="julia", assignee="builder")
    row(
        "work/stripe",
        "Move card payments to Stripe",
        minute=1,
        **{"part-of": "work/apple-pay", "status": "resolved"},
    )
    row(
        "work/double",
        "Fix the double charges",
        minute=2,
        assignee="builder",
        **{"part-of": "work/apple-pay", "depends-on": "work/stripe"},
    )
    row(
        "work/checkout",
        "Add Apple Pay to checkout",
        minute=3,
        assignee="builder",
        **{"part-of": "work/apple-pay", "depends-on": ["work/stripe"]},
    )
    row(
        "work/iphone",
        "Test it on a real iPhone",
        minute=4,
        assignee="julia",
        **{"part-of": "work/apple-pay", "depends-on": "work/checkout"},
    )
    row(
        "work/turn-on",
        "Turn it on for everyone",
        minute=5,
        **{"part-of": "work/apple-pay", "depends-on": ["work/iphone", "work/double"]},
    )
    row("work/old-form", "Remove the old card form", minute=6, **{"depends-on": "work/apple-pay"})
    row("work/alerts", "Alert us when payments fail", minute=7, assignee="reviewer")
    row("work/done-already", "Something finished", minute=8, status="resolved")


class TestContract:
    def test_part_states_and_fields_match_the_contract(self):
        assert list(board.PART_STATES) == CONTRACT["part_states"]
        assert list(BoardPart.model_fields) == CONTRACT["part_fields"]
        assert [f for f in BoardEpic.model_fields if f not in BoardPart.model_fields] == CONTRACT[
            "epic_fields"
        ]
        assert list(waiting.KINDS) == CONTRACT["waiting_kinds"]
        assert list(WaitingItem.model_fields) == CONTRACT["waiting_fields"]


class TestEpics:
    def test_an_epic_has_its_progress_its_lead_and_a_path_that_branches(self, apple_pay):
        read = board.board(ROOM, NOW)
        [epic] = read["epics"]
        assert epic["key"] == "work/apple-pay"
        assert (epic["done"], epic["total"]) == (1, 5)
        assert epic["lead"] == "builder"
        assert epic["steps"] == [
            ["work/stripe"],
            ["work/double", "work/checkout"],
            ["work/iphone"],
            ["work/turn-on"],
        ]
        states = {p["key"]: p["state"] for p in epic["path"]}
        assert states == {
            "work/stripe": "done",
            "work/double": "working",
            "work/checkout": "working",
            "work/iphone": "waiting",
            "work/turn-on": "waiting",
        }

    def test_a_status_report_is_read_but_not_listed(self, apple_pay):
        row("status/launch", "Stripe is live", minute=9)
        row("work/after", "After the report", minute=10, **{"depends-on": "status/launch"})
        tasks = {t["key"]: t for t in board.board(ROOM, NOW)["tasks"]}
        assert "status/launch" not in tasks
        assert tasks["work/after"]["waiting_on"] == ["status/launch"]

    def test_other_open_tasks_stand_alone_and_settled_ones_leave(self, apple_pay):
        read = board.board(ROOM, NOW)
        assert [t["key"] for t in read["tasks"]] == ["work/old-form", "work/alerts"]
        old = read["tasks"][0]
        assert (old["state"], old["waiting_on"]) == ("waiting", ["work/apple-pay"])
        assert read["tasks"][1]["state"] == "working"

    def test_each_part_carries_the_newest_line_said_in_its_thread(self, apple_pay):
        write_transcript(
            ROOM,
            [
                said(1, "builder", "Starting on the double charges.", 1, thread("double")),
                said(2, "reviewer", "Approved #504.\nCI passed too.", 2, thread("double")),
                said(3, "builder", "Unrelated, in the room.", 3),
            ],
        )
        [epic] = board.board(ROOM, NOW)["epics"]
        double = next(p for p in epic["path"] if p["key"] == "work/double")
        assert double["latest"]["sender"] == "reviewer"
        assert double["latest"]["text"] == "Approved #504."
        assert next(p for p in epic["path"] if p["key"] == "work/stripe")["latest"] is None

    def test_a_cycle_goes_last_rather_than_breaking_the_read(self):
        row("work/e", "Epic", minute=0)
        row("work/a", "A", minute=1, **{"part-of": "work/e"})
        row("work/b", "B", minute=2, **{"part-of": "work/e", "depends-on": "work/c"})
        row("work/c", "C", minute=3, **{"part-of": "work/e", "depends-on": "work/b"})
        [epic] = board.board(ROOM, NOW)["epics"]
        assert epic["steps"] == [["work/a"], ["work/b", "work/c"]]

    def test_a_nested_epic_is_a_part_of_its_parent_with_its_own_count(self):
        row("work/top", "Top", minute=0)
        row("work/mid", "Mid", minute=1, **{"part-of": "work/top"})
        row("work/leaf", "Leaf", minute=2, **{"part-of": "work/mid", "status": "resolved"})
        read = board.board(ROOM, NOW)
        assert [e["key"] for e in read["epics"]] == ["work/top"]
        [mid] = read["epics"][0]["path"]
        assert (mid["parts"], mid["parts_done"]) == (1, 1)


class TestRoutes:
    async def test_the_board_and_one_row_read_over_http(self, client, apple_pay):
        await client.post("/api/rooms", json={"name": ROOM})
        read = (await client.get(f"/api/rooms/{ROOM}/board")).json()
        assert [e["key"] for e in read["epics"]] == ["work/apple-pay"]
        one = (await client.get(f"/api/rooms/{ROOM}/board/work/apple-pay")).json()
        assert one["total"] == 5
        done = (await client.get(f"/api/rooms/{ROOM}/board/work/done-already")).json()
        assert (done["state"], done["path"]) == ("done", [])
        missing = await client.get(f"/api/rooms/{ROOM}/board/work/nope")
        assert missing.status_code == 404

    async def test_waiting_reads_over_http(self, client, apple_pay):
        await client.post("/api/rooms", json={"name": ROOM})
        resp = await client.get(f"/api/rooms/{ROOM}/waiting", params={"for": "@julia"})
        assert resp.status_code == 200
        assert resp.json()["handle"] == "julia"


class TestWaiting:
    def test_an_unanswered_ask_a_task_and_nothing_twice(self, apple_pay, monkeypatch):
        # The room's live log, as a running hub holds it.
        monkeypatch.setattr(
            waiting,
            "_records",
            lambda room: [
                said(
                    1,
                    "builder",
                    "@julia refund automatically, or send to support?",
                    1,
                    thread("double"),
                ),
                said(2, "builder", "@julia and one more thing", 2, thread("double")),
                said(3, "builder", "@julia answered already?", 3, thread("checkout")),
                said(4, "julia", "Yes, go ahead.", 4, thread("checkout")),
                said(5, "builder", "@julia this one's done", 5, thread("done-already")),
                said(6, "builder", "@reviewer not for julia", 6, thread("alerts")),
            ],
        )
        items = waiting.waiting(ROOM, "julia", NOW)
        assert [(i["kind"], i["key"]) for i in items] == [("ask", "work/double")]
        ask = items[0]
        assert ask["text"] == "@julia and one more thing"
        assert ask["count"] == 2
        assert (ask["epic"], ask["epic_title"]) == ("work/apple-pay", "Apple Pay for everyone")

    def test_a_task_waits_on_its_holder_once_nothing_is_ahead_of_it(self, apple_pay):
        # The iPhone test waits on checkout, so it isn't waiting on julia yet.
        assert waiting.waiting(ROOM, "julia", NOW) == []
        reviewer = waiting.waiting(ROOM, "reviewer", NOW)
        assert [(i["kind"], i["key"]) for i in reviewer] == [("task", "work/alerts")]
        # builder leads the epic, but it has open parts: those are what wait on builder.
        assert [i["key"] for i in waiting.waiting(ROOM, "builder", NOW)] == [
            "work/checkout",
            "work/double",
        ]

    def test_a_floor_given_to_the_member_is_its_turn(self, apple_pay, monkeypatch):
        from app.services.room_channels import manager

        floor = Floor(thread("alerts"), "conductor", frozenset({"julia"}))
        monkeypatch.setattr(manager, "floors_of", lambda room: [floor])
        items = waiting.waiting(ROOM, "julia", NOW)
        assert [(i["kind"], i["key"], i["sender"]) for i in items] == [
            ("turn", "work/alerts", "conductor")
        ]
