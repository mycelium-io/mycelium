# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``GET /rooms`` sorts by last activity, not creation order."""

from __future__ import annotations

import time

import pytest

from app.services.filesystem import ensure_room_structure, get_room_dir
from app.services.persister import TranscriptRecord, append_transcript


async def _create_room(client, name: str) -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code == 201, resp.text


def _touch_transcript(room: str) -> None:
    """Append a transcript record to ``room``, bumping its file mtime to now."""
    ensure_room_structure(get_room_dir(room))
    append_transcript(
        room,
        TranscriptRecord(
            message_id="m1",
            sender="agent",
            kind="broadcast",
            subkind=None,
            content={"text": "hi"},
            recorded_at="2026-01-01T00:00:00+00:00",
        ),
    )


@pytest.mark.asyncio
async def test_list_rooms_orders_by_last_activity(client) -> None:
    # Created oldest-first: "alpha", then "beta", then "gamma".
    await _create_room(client, "alpha")
    await _create_room(client, "beta")
    await _create_room(client, "gamma")

    # "alpha" has no messages (falls back to its old created_at). "beta" gets a
    # message now, so it should sort ahead of the newer-but-quiet "gamma".
    _touch_transcript("beta")

    resp = await client.get("/api/rooms")
    assert resp.status_code == 200
    rooms = resp.json()
    names = [r["name"] for r in rooms]

    # "beta" was just active, so it leads even though "gamma" was created later.
    assert names.index("beta") < names.index("gamma")
    # "alpha" has never had a message and was created first: it sorts last.
    assert names[-1] == "alpha"

    # Each room surfaces last_activity; the active one's is newer than its own
    # created_at (the field the UI renders instead of creation time).
    beta = next(r for r in rooms if r["name"] == "beta")
    assert beta["last_activity"] is not None
    assert beta["last_activity"] >= beta["created_at"]


@pytest.mark.asyncio
async def test_list_rooms_falls_back_to_created_at_without_transcript(client) -> None:
    await _create_room(client, "quiet-old")
    time.sleep(0.01)
    await _create_room(client, "quiet-new")

    resp = await client.get("/api/rooms")
    assert resp.status_code == 200
    names = [r["name"] for r in resp.json()]
    assert names.index("quiet-new") < names.index("quiet-old")
