# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Walking back through a room's history over HTTP (issue #654).

The list route's end of the contract: ``cursor`` in, ``next_cursor``/``has_more``
out, pages that stay coherent while the room keeps talking. The primitive's own
properties are covered in ``test_pagination``; these assert the route wires it up
and that the transcript-backed read path pages the same as the in-memory one.
"""

import pytest

from app.services import l9, persister
from app.services.filesystem import get_room_dir
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content


def _record(seq: int, *, sender: str = "alice", text: str | None = None):
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode="urn:ioc:mycelium:episode:r:s",
        sender=sender,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic="urn:concept:mycelium:r",
        message_id=f"m-{seq:04d}",
        payload_type="reply",
    )
    record = persister.record_from(
        env, serialize_content(env, extra={"content": text or f"line {seq}"})
    )
    # One second apart so the walk has an unambiguous chronological order.
    record.recorded_at = f"2026-08-20T10:{seq // 60:02d}:{seq % 60:02d}+00:00"
    return record


async def _seed(client, room: str, count: int) -> None:
    await client.post("/api/rooms", json={"name": room})
    get_room_dir(room)
    for i in range(count):
        persister.append_transcript(room, _record(i))


async def _walk_all(client, room: str, *, limit: int, on_page=None) -> list[str]:
    """Follow ``next_cursor`` to the end, collecting message content."""
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(50):  # guard: a broken cursor must fail the test, not hang it
        url = f"/api/rooms/{room}/messages?limit={limit}"
        if cursor:
            url += f"&cursor={cursor}"
        body = (await client.get(url)).json()
        seen.extend(m["content"] for m in body["messages"])
        if not body["has_more"]:
            return seen
        cursor = body["next_cursor"]
        assert cursor, "has_more with no cursor leaves the client stranded"
        if on_page is not None:
            await on_page()
    pytest.fail("cursor walk did not terminate")


@pytest.mark.asyncio
async def test_a_walk_back_reaches_history_past_the_first_page(client):
    """The bug: a room deeper than one window had its older messages unreachable."""
    await _seed(client, "deep-room", 25)

    walked = await _walk_all(client, "deep-room", limit=10)

    assert walked == [f"line {i}" for i in reversed(range(25))]


@pytest.mark.asyncio
async def test_pages_stay_coherent_while_the_room_keeps_talking(client):
    """New messages land at the head mid-walk; the walk back is unaffected."""
    room = "live-room"
    await _seed(client, room, 20)
    extra = iter(range(100, 110))

    async def post_one():
        persister.append_transcript(room, _record(next(extra), text="live"))

    walked = await _walk_all(client, room, limit=6, on_page=post_one)

    # Every history row, in order, exactly once — and the rows that arrived at
    # the head after the walk began stay out of it (they reach a live client over
    # SSE, not by being shuffled into a page of the past).
    assert walked == [f"line {i}" for i in reversed(range(20))]


@pytest.mark.asyncio
async def test_the_first_page_is_the_newest_messages(client):
    await _seed(client, "newest-room", 12)

    body = (await client.get("/api/rooms/newest-room/messages?limit=4")).json()

    assert [m["content"] for m in body["messages"]] == ["line 11", "line 10", "line 9", "line 8"]
    assert body["total"] == 12
    assert body["has_more"] is True


@pytest.mark.asyncio
async def test_a_short_room_reports_the_end_of_history(client):
    await _seed(client, "short-room", 3)

    body = (await client.get("/api/rooms/short-room/messages?limit=50")).json()

    assert body["has_more"] is False
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_a_filtered_walk_pages_only_the_matching_rows(client):
    """Filters compose with the cursor — a page is a page of the filtered list."""
    room = "filtered-room"
    await client.post("/api/rooms", json={"name": room})
    get_room_dir(room)
    for i in range(12):
        persister.append_transcript(room, _record(i, sender="alice" if i % 2 else "bob"))

    first = (await client.get(f"/api/rooms/{room}/messages?limit=3&sender=alice")).json()
    second = (
        await client.get(
            f"/api/rooms/{room}/messages?limit=3&sender=alice&cursor={first['next_cursor']}"
        )
    ).json()

    assert first["total"] == 6
    assert [m["content"] for m in first["messages"]] == ["line 11", "line 9", "line 7"]
    assert [m["content"] for m in second["messages"]] == ["line 5", "line 3", "line 1"]


@pytest.mark.asyncio
async def test_offset_paging_still_works_for_callers_that_have_not_migrated(client):
    await _seed(client, "offset-room", 10)

    body = (await client.get("/api/rooms/offset-room/messages?limit=3&offset=3")).json()

    assert [m["content"] for m in body["messages"]] == ["line 6", "line 5", "line 4"]


@pytest.mark.asyncio
async def test_a_bad_cursor_is_a_400_not_a_silent_first_page(client):
    await _seed(client, "bad-cursor-room", 5)

    resp = await client.get("/api/rooms/bad-cursor-room/messages?cursor=not-a-cursor")

    assert resp.status_code == 400
