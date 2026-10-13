# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where the room says an agent is responding: the thread its wake told it to
reply in, nowhere named when that's ambiguous, and not overridden by a guess."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services import activity, message_format, wake_digest
from app.services.persister import TranscriptRecord

ROOM = "place-room"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
T1 = "urn:ioc:mycelium:episode:place-room:t1"
T2 = "urn:ioc:mycelium:episode:place-room:t2"


def _said(n: int, sender: str, text: str, episode: str | None = None) -> TranscriptRecord:
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
                    "message": {"episode": episode or message_format.live_episode_urn(ROOM)},
                    "participants": {"actors": [{"id": sender}]},
                },
                "payload": {"type": "message"},
            },
        },
        recorded_at=(NOW - timedelta(minutes=10 - n)).isoformat(),
    )


WAKE = {"handle": "builder", "episode": T2}


def test_it_is_the_one_thread_that_asked():
    records = [_said(1, "hay", "@builder the totals?", T1), _said(2, "hay", "@builder and tax", T1)]
    assert wake_digest.reply_episode(ROOM, WAKE, records) == T1


def test_it_names_no_thread_when_asks_came_from_several():
    records = [_said(1, "hay", "@builder the totals?", T1), _said(2, "scout", "@builder ok?", T2)]
    assert wake_digest.reply_episode(ROOM, WAKE, records) is None


def test_the_room_itself_is_no_thread():
    records = [_said(1, "hay", "@builder quick one")]
    assert wake_digest.reply_episode(ROOM, WAKE, records) is None


def test_only_asks_since_its_last_turn_count():
    records = [
        _said(1, "hay", "@builder old ask", T1),
        _said(2, "builder", "done with that", T1),
        _said(3, "hay", "@builder new ask", T2),
    ]
    assert wake_digest.reply_episode(ROOM, WAKE, records) == T2


def test_with_nothing_asked_it_is_where_the_wake_was_raised():
    assert wake_digest.reply_episode(ROOM, WAKE, []) == T2


def test_a_responding_stands_until_done_or_its_ttl(monkeypatch: pytest.MonkeyPatch):
    clock = [1000.0]
    monkeypatch.setattr(activity.time, "monotonic", lambda: clock[0])
    activity.signal(ROOM, "@Builder", "responding", episode=T1)
    assert activity.is_responding(ROOM, "builder")
    clock[0] += activity.TTL_S
    assert not activity.is_responding(ROOM, "builder")
    activity.signal(ROOM, "builder", "responding")
    activity.signal(ROOM, "builder", "done")
    assert not activity.is_responding(ROOM, "builder")
