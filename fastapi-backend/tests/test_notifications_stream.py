# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The aggregate notification stream: every room's activity, one subscription.

Drives ``_sse_notifications`` directly (not over HTTP) — the generator is the
task under test; the surrounding ``StreamingResponse``/route wiring mirrors the
already-untested ``_sse_from_channel`` endpoints.
"""

import asyncio
import json

import pytest

from app.bus import bus, room_channel
from app.routes.stream import _sse_notifications


class _FakeRequest:
    """Never reports disconnected; tests end the generator with ``aclose()``."""

    async def is_disconnected(self) -> bool:
        return False


async def _next_data_frame(gen) -> dict:
    """Pull frames until a ``data:`` one arrives (skipping ping/keep-alive)."""
    while True:
        frame = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        if frame.startswith("data: "):
            return json.loads(frame[len("data: ") :])


@pytest.mark.asyncio
async def test_includes_activity_from_a_room_that_predates_the_connection(client):
    await client.post("/api/rooms", json={"name": "eng-room"})

    gen = _sse_notifications(_FakeRequest())  # type: ignore[arg-type]
    try:
        opening = await gen.__anext__()
        assert opening.startswith("event: ping")

        bus.publish(
            room_channel("eng-room"),
            {"room_name": "eng-room", "message_type": "l9_exchange", "content": "{}"},
        )
        frame = await _next_data_frame(gen)
        assert frame["room_name"] == "eng-room"
        assert frame["message_type"] == "l9_exchange"
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_follows_a_room_created_after_the_connection(client):
    gen = _sse_notifications(_FakeRequest())  # type: ignore[arg-type]
    try:
        await gen.__anext__()

        create_resp = await client.post("/api/rooms", json={"name": "new-room"})
        assert create_resp.status_code == 201
        created = await _next_data_frame(gen)
        assert created == {
            "type": "room_created",
            "room_name": "new-room",
            "mas_id": None,
            "created_at": created["created_at"],
        }

        bus.publish(
            room_channel("new-room"),
            {"room_name": "new-room", "message_type": "coordination_join", "content": "{}"},
        )
        frame = await _next_data_frame(gen)
        assert frame["room_name"] == "new-room"
        assert frame["message_type"] == "coordination_join"
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_drops_subscription_on_room_deleted(client):
    await client.post("/api/rooms", json={"name": "gone-room"})
    gen = _sse_notifications(_FakeRequest())  # type: ignore[arg-type]
    try:
        await gen.__anext__()

        delete_resp = await client.delete("/api/rooms/gone-room")
        assert delete_resp.status_code == 204
        deleted = await _next_data_frame(gen)
        assert deleted == {"type": "room_deleted", "room_name": "gone-room"}

        # The generator unsubscribed on the room_deleted frame — the bus has no
        # remaining subscriber for that room's channel. Checked directly rather
        # than waiting out the generator's 15s keep-alive timeout for a frame
        # that (correctly) never arrives.
        assert room_channel("gone-room") not in bus._subs
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_cleans_up_all_subscriptions_on_close(client):
    await client.post("/api/rooms", json={"name": "room-a"})
    await client.post("/api/rooms", json={"name": "room-b"})

    gen = _sse_notifications(_FakeRequest())  # type: ignore[arg-type]
    await gen.__anext__()
    assert room_channel("room-a") in bus._subs
    assert room_channel("room-b") in bus._subs

    await gen.aclose()

    assert room_channel("room-a") not in bus._subs
    assert room_channel("room-b") not in bus._subs
