# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``GET /rooms/{room}/messages/wire`` — transcript replay that backfills the channel and Stream.

The channel and Stream are fed live only by the SSE bus (no history), so a freshly opened
tab starts empty. This endpoint replays the durable transcript through the same
frame shape the bus pushes, envelope intact — the part the conversational messages
API drops.
"""

import json

import pytest

from app.services.persister import TranscriptRecord, append_transcript


async def _create_room(client, name: str) -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code == 201, resp.text


def _message_record(
    message_id: str, sender: str, kind: str, text: str, data: dict
) -> TranscriptRecord:
    """A transcript record carrying a message, like a connector's reply."""
    return TranscriptRecord(
        message_id=message_id,
        sender=sender,
        kind=kind,
        subkind=None,
        content={
            "content": text,
            "l9": {
                "header": {
                    "kind": kind,
                    "message": {"id": message_id, "parents": [], "episode": "urn:x:1"},
                },
                "payload": {"type": "data", "data": data},
            },
        },
        recorded_at="2026-01-01T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_message_history_replays_frames_with_envelope(client) -> None:
    await _create_room(client, "wire")
    append_transcript(
        "wire", _message_record("m1", "avery", "exchange", "cap at 30%", {"round": 1})
    )

    resp = await client.get("/api/rooms/wire/messages/wire")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1

    frame = rows[0]
    # The bus frame shape the channel and Stream read: l9_<kind> + the full envelope in content.
    assert frame["message_type"] == "l9_exchange"
    assert frame["sender_handle"] == "avery"
    content = json.loads(frame["content"])
    assert content["l9"]["header"]["kind"] == "exchange"
    assert content["l9"]["payload"]["data"] == {"round": 1}


@pytest.mark.asyncio
async def test_a_frame_names_the_id_the_history_read_gives_its_message(client) -> None:
    """A message's frame and its history row are told apart by nothing but id
    otherwise, so the frame carries the row's id too."""
    await _create_room(client, "wire")
    reply = TranscriptRecord(
        message_id="m1",
        sender="avery",
        kind="exchange",
        subkind=None,
        content={
            "content": "cap at 30%",
            "l9": {
                "header": {
                    "kind": "exchange",
                    "message": {
                        "id": "m1",
                        "parents": [],
                        "episode": "urn:ioc:mycelium:episode:wire:live",
                    },
                },
                "payload": {"type": "reply", "data": {"action": "reply"}},
            },
        },
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    append_transcript("wire", reply)

    frame = (await client.get("/api/rooms/wire/messages/wire")).json()[0]
    row = (await client.get("/api/rooms/wire/messages")).json()["messages"][0]
    assert frame["id"] == "m1"
    assert frame["read_id"] == row["id"]


@pytest.mark.asyncio
async def test_message_history_orders_oldest_first_and_limits(client) -> None:
    await _create_room(client, "wire")
    for i in range(5):
        append_transcript("wire", _message_record(f"m{i}", "a", "exchange", f"t{i}", {"i": i}))

    rows = (await client.get("/api/rooms/wire/messages/wire?limit=3")).json()
    # Last 3 records, oldest-first.
    ids = [json.loads(r["content"])["l9"]["header"]["message"]["id"] for r in rows]
    assert ids == ["m2", "m3", "m4"]


@pytest.mark.asyncio
async def test_message_history_empty_for_room_without_traffic(client) -> None:
    await _create_room(client, "quiet")
    assert (await client.get("/api/rooms/quiet/messages/wire")).json() == []
