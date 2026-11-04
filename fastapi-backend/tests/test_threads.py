# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Threads started from a message: a conversation about it, not a task.

A thread is a ``threads/`` memory naming the message it came from. It has a
thread of its own like any memory, never shows on the board, and the light
memory list says what has been said in it, worked out from the history.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services import message_format, persister, threads, wake_digest
from app.services.message_models import Kind
from app.services.message_slim import serialize_content

ROOM = "checkout"
START = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
ALERT = "Adding an alert for when payments start failing.\nSo we hear before customers do."


def _say(n: int, sender: str, text: str, episode: str | None = None):
    """One message in the room's history, ``n`` minutes in."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=episode or message_format.live_episode_urn(ROOM),
        sender=sender,
        recipients=[message_format.SYSTEM_ACTOR_ID],
        topic=f"urn:concept:mycelium:{ROOM}",
        message_id=f"m-{n:03d}",
        payload_type="reply",
    )
    record = persister.record_from(env, serialize_content(env, extra={"content": text}))
    record.message_id = f"m-{n:03d}"
    record.recorded_at = (START + timedelta(minutes=n)).isoformat()
    persister.append_transcript(ROOM, record)
    persister._conversational_cache.clear()
    return str(persister.read_id(record))


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


@pytest.fixture
async def room(client):
    resp = await client.post("/api/rooms", json={"name": ROOM})
    assert resp.status_code in (200, 201), resp.text
    return ROOM


async def _start(client, message: str, handle: str = "reviewer"):
    return await client.post(f"/api/rooms/{ROOM}/threads", json={"from": message, "handle": handle})


async def _summary(client, key: str, **params) -> dict:
    listed = (await client.get(f"/api/rooms/{ROOM}/memory/summaries", params=params)).json()
    return next(s for s in listed if s["key"] == key)


async def test_a_thread_is_named_after_its_message_and_started_once(client, room):
    alert = _say(1, "operator", ALERT)
    resp = await _start(client, alert)
    assert resp.status_code == 201, resp.text
    thread = resp.json()
    assert thread["key"] == "threads/adding-an-alert-for-when-payments-start-failing"
    assert thread["value"] == {"text": "Adding an alert for when payments start failing."}
    assert thread["meta"]["from"] == alert
    assert thread["created_by"] == "reviewer"
    assert thread["episode"]

    again = await _start(client, alert, handle="builder")
    assert again.status_code == 200
    assert again.json()["key"] == thread["key"]
    assert again.json()["episode"] == thread["episode"]


async def test_a_thread_needs_a_message_in_the_room_s_own_channel(client, room):
    assert (await _start(client, "no-such-message")).status_code == 404
    started = (await _start(client, _say(1, "operator", ALERT))).json()
    inside = _say(2, "builder", "five percent over ten minutes", episode=started["episode"])
    assert (await _start(client, inside)).status_code == 404
    gone = await client.post("/api/rooms/elsewhere/threads", json={"from": "x", "handle": "b"})
    assert gone.status_code == 404


async def test_a_long_first_line_is_cut_on_a_word():
    title = threads.title_of("Ship the wallet screen " * 6)
    assert len(title) <= threads.TITLE_CHARS + 1
    assert title.endswith("…")
    assert not title[:-1].endswith(" ")


async def test_the_list_says_what_has_been_said_in_it_worked_out_on_read(client, room):
    started = (await _start(client, _say(1, "operator", ALERT))).json()
    key, episode = started["key"], started["episode"]
    quiet = await _summary(client, key)
    assert quiet["thread"] == {
        "replies": 0,
        "last_reply_at": None,
        "repliers": [],
        "last_reply": None,
    }
    version = quiet["version"]

    _say(2, "reviewer", "What counts as failing?\nOne declined card is normal.", episode)
    _say(3, "builder", "More than 5% over ten minutes.", episode)
    _say(4, "reviewer", "Good, send it to the room.", episode)
    # The hub's own post in a thread is a report on it, not a reply.
    _say(5, message_format.SYSTEM_ACTOR_ID, "thread opened", episode)
    # Said in the room, not in the thread.
    _say(6, "builder", "unrelated", None)

    said = await _summary(client, key)
    assert said["thread"]["replies"] == 3
    assert said["thread"]["repliers"] == ["reviewer", "builder"]
    assert said["thread"]["last_reply"] == "Good, send it to the room."
    assert said["thread"]["last_reply_at"].startswith("2026-11-04T09:04")
    assert said["version"] == version, "a reply rewrites nothing"


async def test_a_reply_moves_the_list_s_cache_stamp(client, room):
    started = (await _start(client, _say(1, "operator", ALERT))).json()
    first = await client.get(f"/api/rooms/{ROOM}/memory/summaries")
    etag = first.headers["etag"]
    cached = await client.get(
        f"/api/rooms/{ROOM}/memory/summaries", headers={"If-None-Match": etag}
    )
    assert cached.status_code == 304
    _say(2, "reviewer", "What counts as failing?", started["episode"])
    moved = await client.get(f"/api/rooms/{ROOM}/memory/summaries", headers={"If-None-Match": etag})
    assert moved.status_code == 200


async def test_only_a_thread_carries_what_was_said(client, room):
    await _start(client, _say(1, "operator", ALERT))
    await client.post(
        f"/api/rooms/{ROOM}/tasks", json={"title": "Fix the receipt email", "handle": "builder"}
    )
    listed = (await client.get(f"/api/rooms/{ROOM}/memory/summaries")).json()
    assert {s["key"]: s["thread"] is not None for s in listed if "/" in s["key"]} == {
        "threads/adding-an-alert-for-when-payments-start-failing": True,
        "work/fix-the-receipt-email": False,
    }


async def test_a_thread_is_never_a_board_row(client, room):
    started = (await _start(client, _say(1, "operator", ALERT))).json()
    board = (await client.get(f"/api/rooms/{ROOM}/board")).text
    assert started["key"] not in board


async def test_a_task_made_from_a_thread_points_back_at_it_once(client, room):
    key = (await _start(client, _say(1, "operator", ALERT))).json()["key"]
    resp = await client.post(f"/api/rooms/{ROOM}/threads/{key}/task", json={"handle": "builder"})
    assert resp.status_code == 201, resp.text
    task = resp.json()
    assert task["key"].startswith("work/adding-an-alert")
    assert task["meta"]["relates-to"] == key
    assert task["episode"]
    again = await client.post(f"/api/rooms/{ROOM}/threads/{key}/task", json={"handle": "b"})
    assert again.status_code == 200
    assert again.json()["key"] == task["key"]
    work = await client.post(f"/api/rooms/{ROOM}/threads/{task['key']}/task", json={"handle": "b"})
    assert work.status_code == 422


async def test_a_wake_calls_it_a_thread(client, room):
    key = "threads/adding-an-alert-for-when-payments-start-failing"
    assert wake_digest._place(ROOM, (key, "Adding an alert")) == f'thread "Adding an alert" ({key})'
    task = ("work/fix-the-receipt-email", "Fix the receipt email")
    assert wake_digest._place(ROOM, task) == '"Fix the receipt email" (work/fix-the-receipt-email)'
