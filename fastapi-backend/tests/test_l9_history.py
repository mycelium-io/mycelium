# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``GET /rooms/{room}/messages/l9`` — transcript replay that backfills the inspector.

The live L9 inspector is fed only by the SSE bus (no history), so a freshly opened
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


def _l9_record(message_id: str, sender: str, kind: str, text: str, data: dict) -> TranscriptRecord:
    """A transcript record carrying an L9 envelope, like a connector's reply."""
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
async def test_l9_history_replays_frames_with_envelope(client) -> None:
    await _create_room(client, "wire")
    append_transcript("wire", _l9_record("m1", "avery", "exchange", "cap at 30%", {"round": 1}))

    resp = await client.get("/api/rooms/wire/messages/l9")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1

    frame = rows[0]
    # The bus frame shape the inspector reads: l9_<kind> + the full envelope in content.
    assert frame["message_type"] == "l9_exchange"
    assert frame["sender_handle"] == "avery"
    content = json.loads(frame["content"])
    assert content["l9"]["header"]["kind"] == "exchange"
    assert content["l9"]["payload"]["data"] == {"round": 1}


@pytest.mark.asyncio
async def test_l9_history_orders_oldest_first_and_limits(client) -> None:
    await _create_room(client, "wire")
    for i in range(5):
        append_transcript("wire", _l9_record(f"m{i}", "a", "exchange", f"t{i}", {"i": i}))

    rows = (await client.get("/api/rooms/wire/messages/l9?limit=3")).json()
    # Last 3 records, oldest-first.
    ids = [json.loads(r["content"])["l9"]["header"]["message"]["id"] for r in rows]
    assert ids == ["m2", "m3", "m4"]


@pytest.mark.asyncio
async def test_l9_history_empty_for_room_without_traffic(client) -> None:
    await _create_room(client, "quiet")
    assert (await client.get("/api/rooms/quiet/messages/l9")).json() == []
