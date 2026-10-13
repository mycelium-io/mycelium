# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What each wake delivered to an agent: one line per wake, ids only, with why.

Tells "it was told and didn't act" from "it was never woken with it", which the
transcript alone can't.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import settings
from app.services import message_format, room_channels, wake_digest, wake_log
from app.services.persister import TranscriptRecord
from tests.fakes import FakeSlimClient

ROOM = "wakes-room"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def room(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    from app.services.filesystem import ensure_room_structure, get_room_dir

    ensure_room_structure(get_room_dir(ROOM))
    yield ROOM


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> room_channels.RoomChannelManager:
    monkeypatch.setattr(settings, "SLIM_ENABLED", True)
    monkeypatch.setattr(room_channels, "node_reachable", lambda _endpoint: True)
    monkeypatch.setattr(room_channels, "SlimClient", FakeSlimClient)
    monkeypatch.setattr(room_channels.RoomChannelManager, "_start_persister", lambda self, m: None)
    return room_channels.RoomChannelManager(endpoint="http://node", default_workspace="ws")


def _said(n: int, sender: str, text: str, minutes_ago: int) -> TranscriptRecord:
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
                    "message": {"episode": message_format.live_episode_urn(ROOM)},
                    "participants": {"actors": [{"id": sender}]},
                },
                "payload": {"type": "message"},
            },
        },
        recorded_at=(NOW - timedelta(minutes=minutes_ago)).isoformat(),
    )


def _lines() -> list[dict]:
    from app.services.filesystem import get_room_dir

    path = get_room_dir(ROOM) / wake_log.FILENAME
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


RECORDS = [
    _said(1, "builder", "on it", 30),
    _said(2, "hay", "@builder can you check the receipt totals?", 20),
    _said(3, "scout", "unrelated", 10),
    _said(4, "hay", "@builder and the refunds too", 5),
]


def test_a_wake_covers_the_messages_that_asked_for_its_agent():
    covered = wake_digest.coverage({"handle": "builder"}, RECORDS)
    assert covered == {"messages": ["m2", "m4"], "range": ["m2", "m4"]}


def test_a_delivered_wake_is_recorded_once_with_its_reason_and_messages(manager):
    manager.set_herdr_presence(ROOM, {"builder": "idle"})
    manager.enqueue_herdr_wake(ROOM, "builder", sender="hay")
    (wake,) = manager.drain_herdr_wakes(ROOM)
    assert wake["id"]

    wake_log.handed(ROOM, wake, wake_digest.coverage(wake, RECORDS))
    # Written at once, before the runner says anything, so a restart can't lose it.
    (line,) = _lines()
    assert line["outcome"] == "handed"

    assert wake_log.report(ROOM, wake["id"], delivered=True)
    (record,) = wake_log.read(ROOM)
    assert record["agent"] == "builder"
    assert record["reason"] == "mention"
    assert record["from"] == "hay"
    assert record["messages"] == ["m2", "m4"]
    assert record["outcome"] == "delivered"
    assert record["settled_at"]
    # A repeated report records nothing twice, and no text is kept.
    assert not wake_log.report(ROOM, wake["id"], delivered=False, why="late")
    assert len(_lines()) == 2
    assert wake_log.read(ROOM)[0]["outcome"] == "delivered"
    assert not any("content" in x or "prompt" in x for x in _lines())


def test_a_wake_handed_before_a_restart_is_still_there(manager):
    # The hub's memory is gone after a restart; the line on disk isn't, and the
    # runner's report still settles it once the hub is back.
    wake_log.handed(ROOM, {"id": "w1", "handle": "builder", "reason": "mention"}, {})
    assert wake_log.read(ROOM)[0]["outcome"] == "handed"
    assert wake_log.report(ROOM, "w1", delivered=True)
    assert wake_log.read(ROOM)[0]["outcome"] == "delivered"


def test_a_held_wake_is_recorded_when_it_is_finally_delivered(manager):
    manager.set_herdr_presence(ROOM, {"builder": "working"})
    manager.enqueue_herdr_wake(ROOM, "builder", sender="hay")
    manager.enqueue_herdr_wake(ROOM, "builder", reason="turn", sender="hay")
    assert manager.drain_herdr_wakes(ROOM) == []
    assert _lines() == []  # held, not yet anything

    manager.set_herdr_presence(ROOM, {"builder": "idle"})
    (wake,) = manager.drain_herdr_wakes(ROOM)
    wake_log.handed(ROOM, wake, wake_digest.coverage(wake, RECORDS))
    wake_log.report(ROOM, wake["id"], delivered=True)
    (record,) = wake_log.read(ROOM)
    assert (record["reason"], record["outcome"]) == ("turn", "delivered")


def test_a_wake_held_too_long_is_dropped_saying_why(manager):
    manager.set_herdr_presence(ROOM, {"builder": "working"})
    manager.enqueue_herdr_wake(ROOM, "builder", sender="hay")
    assert manager.drain_herdr_wakes(ROOM, hold_ttl_s=-1.0) == []
    (record,) = wake_log.read(ROOM)
    assert record["outcome"] == "dropped"
    assert "while it was working" in record["why"]


def test_a_runner_that_couldnt_deliver_says_why():
    wake_log.handed(
        ROOM, {"id": "w1", "handle": "builder", "reason": "assigned", "key": "work/x"}, {}
    )
    wake_log.report(ROOM, "w1", delivered=False, why="no herdr pane here is bound to it")
    (record,) = wake_log.read(ROOM)
    assert record["outcome"] == "dropped"
    assert record["why"] == "no herdr pane here is bound to it"
    assert record["task"] == "work/x"


def test_a_report_for_a_wake_the_log_never_handed_records_nothing():
    assert not wake_log.report(ROOM, "nope", delivered=True)
    assert _lines() == []


def test_a_mention_of_an_agent_nothing_runs_is_unreached(manager, monkeypatch):
    from app.services import principals

    monkeypatch.setattr(
        principals, "classify_sender", lambda _r, h: "agent" if h == "builder" else "user"
    )
    manager.enqueue_herdr_wakes_for_mentions(ROOM, "@builder and @julia, look", sender="hay")
    (record,) = wake_log.read(ROOM)  # a person is reached some other way
    assert record["agent"] == "builder"
    # Not lost: it reads the message on its next await. Nothing could be woken.
    assert record["outcome"] == "unreached"
    assert "nothing is running it" in record["why"]


def test_the_log_reads_newest_first_and_by_agent():
    for n, agent in enumerate(["builder", "scout", "builder"]):
        wake_log.dropped(ROOM, {"id": f"w{n}", "handle": agent, "reason": "mention"}, "test")
    assert [r["id"] for r in wake_log.read(ROOM)] == ["w2", "w1", "w0"]
    assert [r["id"] for r in wake_log.read(ROOM, agent="builder", limit=1)] == ["w2"]


def test_the_log_rotates_and_keeps_one_older_file(monkeypatch):
    from app.services.filesystem import get_room_dir

    monkeypatch.setattr(wake_log, "MAX_BYTES", 400)
    for n in range(10):
        wake_log.dropped(ROOM, {"id": f"w{n}", "handle": "builder", "reason": "mention"}, "test")
    assert (get_room_dir(ROOM) / wake_log.ROTATED).exists()
    assert (get_room_dir(ROOM) / wake_log.FILENAME).stat().st_size <= 400
    assert wake_log.read(ROOM, limit=1)[0]["id"] == "w9"


def test_the_runner_reports_through_the_route():
    from app.routes import sessions

    wake_log.handed(
        ROOM, {"id": "w1", "handle": "builder", "reason": "mention"}, {"messages": ["m2"]}
    )
    body = sessions.WakeOutcomes(outcomes=[sessions.WakeOutcome(id="w1", delivered=True)])
    assert asyncio.run(sessions.report_herdr_wakes(ROOM, body)) == {"recorded": 1}
    listed = asyncio.run(sessions.list_wakes(ROOM, agent="@builder"))
    assert [(r["id"], r["outcome"]) for r in listed] == [("w1", "delivered")]
