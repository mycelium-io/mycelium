# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The backward cursor both channel reads page by (issue #899).

``GET /messages`` and ``GET /messages/l9`` answer newest-first inside a window.
Without a way to ask for the window before, a room was whatever its newest page
held and nothing older could be reached. ``before=`` is that ask, defined
relative to content rather than position: an offset shifts under every message
the live stream lands while a reader is walking back, and a stamp does not.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest

from app.services import l9, persister
from app.services.filesystem import get_room_dir
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content

ROOM = "paging-room"
START = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _record(index: int):
    """One transcript line, a minute after the one before it."""
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=f"urn:ioc:mycelium:episode:{ROOM}:live",
        sender="julia",
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=f"urn:concept:mycelium:{ROOM}",
        message_id=f"m-{index:03d}",
        payload_type="reply",
    )
    record = persister.record_from(env, serialize_content(env, extra={"content": f"msg {index}"}))
    record.message_id = f"m-{index:03d}"
    record.recorded_at = (START + timedelta(minutes=index)).isoformat()
    return record


@pytest.fixture
def transcript():
    """Twelve messages, a minute apart, in one room's durable transcript."""
    get_room_dir(ROOM)
    for index in range(12):
        persister.append_transcript(ROOM, _record(index))
    persister._conversational_cache.clear()
    return [f"msg {i}" for i in range(12)]


def _texts(payload) -> list[str]:
    return [m["content"] for m in payload["messages"]]


@pytest.mark.asyncio
async def test_before_serves_the_page_older_than_the_cursor(client, transcript):
    """The walk back: read the newest five, then ask for the five before them."""
    newest = (await client.get(f"/api/rooms/{ROOM}/messages?limit=5")).json()
    assert _texts(newest) == ["msg 11", "msg 10", "msg 9", "msg 8", "msg 7"]

    cursor = quote(newest["messages"][-1]["created_at"])
    older = (await client.get(f"/api/rooms/{ROOM}/messages?limit=5&before={cursor}")).json()
    assert _texts(older) == ["msg 6", "msg 5", "msg 4", "msg 3", "msg 2"]


@pytest.mark.asyncio
async def test_before_is_strict_so_a_page_never_repeats_its_cursor(client, transcript):
    """Strictly before, not at-or-before: a cursor taken from the oldest message
    on screen would otherwise serve that same message again at the head of every
    page, and the walk would never move."""
    page = (await client.get(f"/api/rooms/{ROOM}/messages?limit=4")).json()
    cursor = quote(page["messages"][-1]["created_at"])
    older = (await client.get(f"/api/rooms/{ROOM}/messages?limit=4&before={cursor}")).json()
    assert set(_texts(page)) & set(_texts(older)) == set()


@pytest.mark.asyncio
async def test_total_counts_what_is_older_than_the_cursor(client, transcript):
    """``total`` is the filtered set, not the room — which is how a client knows
    it has reached the start rather than inferring it from a short page."""
    page = (await client.get(f"/api/rooms/{ROOM}/messages?limit=5")).json()
    assert page["total"] == 12

    cursor = quote(page["messages"][-1]["created_at"])
    older = (await client.get(f"/api/rooms/{ROOM}/messages?limit=5&before={cursor}")).json()
    assert older["total"] == 7


@pytest.mark.asyncio
async def test_paging_back_reaches_the_start_and_stops(client, transcript):
    """Every message in the room, walked to in pages, each seen exactly once."""
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        query = f"limit=5{f'&before={quote(cursor)}' if cursor else ''}"
        page = (await client.get(f"/api/rooms/{ROOM}/messages?{query}")).json()
        if not page["messages"]:
            break
        seen.extend(_texts(page))
        cursor = page["messages"][-1]["created_at"]

    assert seen == [f"msg {i}" for i in reversed(range(12))]


@pytest.mark.asyncio
async def test_the_l9_replay_takes_the_same_cursor(client, transcript):
    """The channel's feed is both reads merged, so paging only the prose would
    hand back older pages with the pings and board notices missing."""
    frames = (await client.get(f"/api/rooms/{ROOM}/messages/l9?limit=4")).json()
    assert [f["id"] for f in frames] == ["m-008", "m-009", "m-010", "m-011"]

    cursor = quote(frames[0]["created_at"])
    older = (await client.get(f"/api/rooms/{ROOM}/messages/l9?limit=4&before={cursor}")).json()
    assert [f["id"] for f in older] == ["m-004", "m-005", "m-006", "m-007"]


@pytest.mark.asyncio
async def test_an_unreadable_stamp_survives_the_cursor(client):
    """A transcript line with no usable stamp is kept rather than filtered out:
    dropping it would put a hole in the replay to save a comparison."""
    get_room_dir(ROOM)
    for index in (0, 1):
        persister.append_transcript(ROOM, _record(index))
    undated = _record(2)
    undated.recorded_at = ""
    persister.append_transcript(ROOM, undated)
    persister._conversational_cache.clear()

    cursor = quote(START.isoformat())
    frames = (await client.get(f"/api/rooms/{ROOM}/messages/l9?before={cursor}")).json()
    assert [f["id"] for f in frames] == ["m-002"]
