# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Reading a room's transcript: once in full, then only what was appended.

A busy room's transcript is tens of megabytes, and the app reads it for every
thread a board shows. Parsing all of it on every read after an append held the
event loop long enough that the hub stopped answering its health check.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services import message_format, persister
from app.services.filesystem import get_room_dir
from app.services.persister import TranscriptRecord

ROOM = "busy"
START = datetime(2026, 11, 18, 11, 0, tzinfo=UTC)


def _record(n: int, *, stamped: bool = True) -> TranscriptRecord:
    return TranscriptRecord(
        message_id=f"m{n}",
        sender="builder",
        kind="exchange",
        subkind=None,
        content={
            "content": f"message {n}",
            "envelope": {
                "header": {
                    "kind": "exchange",
                    "message": {"episode": message_format.live_episode_urn(ROOM)},
                    "participants": {"actors": [{"id": "builder"}]},
                },
                "payload": {"type": "message"},
            },
        },
        recorded_at=(START + timedelta(minutes=n)).isoformat() if stamped else "",
    )


@pytest.fixture
def room():
    get_room_dir(ROOM)
    persister._parsed.clear()
    persister._conversational_cache.clear()
    persister.write_transcript(ROOM, [_record(n) for n in range(3)])
    return ROOM


def _parses(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """How many lines each parse was handed, from here on."""
    seen: list[int] = []
    parse = persister._parse_jsonl

    def counting(text: str):
        seen.append(len([ln for ln in text.splitlines() if ln.strip()]))
        return parse(text)

    monkeypatch.setattr(persister, "_parse_jsonl", counting)
    return seen


def test_a_read_after_an_append_parses_only_the_new_lines(room, monkeypatch):
    seen = _parses(monkeypatch)
    assert [r.message_id for r in persister.load_transcript(room)] == ["m0", "m1", "m2"]
    persister.append_transcript(room, _record(3))
    persister.append_transcript(room, _record(4))
    assert [r.message_id for r in persister.load_transcript(room)][-2:] == ["m3", "m4"]
    assert persister.load_transcript(room)[-1].message_id == "m4"
    assert seen == [3, 2, 0]


def test_each_caller_gets_its_own_list(room):
    mine = persister.load_transcript(room)
    mine.append(_record(9))
    assert len(persister.load_transcript(room)) == 3


def test_a_transcript_written_over_is_read_again_in_full(room, monkeypatch):
    persister.load_transcript(room)
    seen = _parses(monkeypatch)
    # Same length or longer, other content: never read as an append.
    persister.write_transcript(room, [_record(n) for n in (7, 8, 9, 10)])
    assert [r.message_id for r in persister.load_transcript(room)] == ["m7", "m8", "m9", "m10"]
    assert seen == [4]
    # Shorter, too.
    persister.write_transcript(room, [_record(5)])
    assert [r.message_id for r in persister.load_transcript(room)] == ["m5"]


def test_a_line_still_being_written_waits_for_its_newline(room):
    persister.load_transcript(room)
    path = get_room_dir(room) / persister.TRANSCRIPT_FILENAME
    line = persister._transcript_line(_record(3))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line[:20])
    assert len(persister.load_transcript(room)) == 3
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line[20:] + "\n")
    assert persister.load_transcript(room)[-1].message_id == "m3"


def test_only_the_rooms_read_most_recently_stay_parsed(room, monkeypatch):
    monkeypatch.setattr(persister, "_PARSED_ROOMS", 2)
    for other in ("quiet", "loud"):
        get_room_dir(other)
        persister.write_transcript(other, [_record(n) for n in range(2)])
    persister.load_transcript(room)
    persister.load_transcript("quiet")
    persister.load_transcript(room)  # read again: now the most recent
    persister.load_transcript("loud")
    kept = {key.split("/rooms/")[1].split("/")[0] for key in persister._parsed}
    assert kept == {room, "loud"}
    # The room that fell out is read in full again, and correctly.
    seen = _parses(monkeypatch)
    assert [r.message_id for r in persister.load_transcript("quiet")] == ["m0", "m1"]
    assert seen == [2]


def test_the_conversation_grows_the_way_a_full_read_would_build_it(room):
    first = persister.conversational_messages(room)
    persister.append_transcript(room, _record(3, stamped=False))
    persister.append_transcript(room, _record(4))
    grown = persister.conversational_messages(room)
    persister._conversational_cache.clear()
    whole = persister.conversational_messages(room)
    assert [m.id for m in grown] == [m.id for m in whole]
    assert [m.created_at for m in grown] == [m.created_at for m in whole]
    # The unstamped one took the stamp before it, as a whole read gives it.
    assert grown[3].created_at == first[2].created_at
