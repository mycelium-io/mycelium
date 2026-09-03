# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The activity signal rides the bus and only the bus."""

from __future__ import annotations

from app.bus import bus, room_channel
from app.services import activity, in_memory_store


def test_a_signal_is_a_bus_frame_and_not_a_message() -> None:
    queue = bus.subscribe(room_channel("r"))
    try:
        frame = activity.signal("r", "aligner", "responding", episode="urn:x")
        assert queue.get_nowait() == frame
    finally:
        bus.unsubscribe(room_channel("r"), queue)

    assert frame["type"] == activity.ACTIVITY_TYPE
    assert frame["message_type"] == activity.ACTIVITY_TYPE
    assert frame["room_name"] == "r"
    assert frame["handle"] == "aligner"
    assert frame["sender_handle"] == "aligner"
    assert frame["state"] == "responding"
    assert frame["episode"] == "urn:x"
    assert frame["ttl_s"] == activity.TTL_S
    # A typing indicator is never a line in the room.
    assert "content" not in frame
    assert in_memory_store.list_messages("r") == []


def test_done_clears_and_names_the_same_handle() -> None:
    queue = bus.subscribe(room_channel("r"))
    try:
        activity.signal("r", "growth", "responding")
        activity.signal("r", "growth", "done")
        first, second = queue.get_nowait(), queue.get_nowait()
    finally:
        bus.unsubscribe(room_channel("r"), queue)
    assert (first["state"], second["state"]) == ("responding", "done")
    assert first["handle"] == second["handle"] == "growth"
    assert first["episode"] is None
