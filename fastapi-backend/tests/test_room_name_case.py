# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room's name ignores case: any spelling is the room made under one.

On a Mac the disk gave ``Marc`` and ``marc`` one folder and one transcript,
while the hub gave them two live channels, so a message an agent sent to
``marc`` showed in Stream (read from the transcript) but never reached a
Channel open on ``Marc``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.room_names import canonical_path
from app.routes import patterns as patterns_route
from app.services.filesystem import canonical_room_name, get_data_dir, get_room_dir


def test_any_spelling_finds_the_room_as_it_was_made() -> None:
    get_room_dir("Marc")
    assert canonical_room_name("marc") == "Marc"
    assert canonical_room_name("MARC") == "Marc"
    assert canonical_room_name("Marc") == "Marc"
    assert canonical_room_name("nowhere") == "nowhere"


def test_two_rooms_that_differ_only_in_case_are_left_as_they_are() -> None:
    """A disk that keeps case apart can hold both from before: each exact
    spelling still finds its own, and another spelling guesses neither."""
    rooms = get_data_dir() / "rooms"
    rooms.mkdir(parents=True, exist_ok=True)
    (rooms / "Ops").mkdir()
    try:
        (rooms / "ops").mkdir()
    except FileExistsError:
        pytest.skip("this disk ignores case, so it can't hold both")
    assert canonical_room_name("ops") == "ops"
    assert canonical_room_name("Ops") == "Ops"
    assert canonical_room_name("OPS") == "OPS"


def test_a_request_path_names_the_room_as_it_was_made() -> None:
    get_room_dir("Marc")
    assert canonical_path("/api/rooms/marc/messages/stream") == "/api/rooms/Marc/messages/stream"
    assert canonical_path("/api/rooms/marc") == "/api/rooms/Marc"
    assert canonical_path("/api/rooms") == "/api/rooms"
    assert canonical_path("/api/rooms/other/messages") == "/api/rooms/other/messages"
    assert canonical_path("/health") == "/health"


@pytest.mark.asyncio
async def test_every_spelling_reaches_the_same_room(client) -> None:
    created = await client.post("/api/rooms", json={"name": "Marc"})
    assert created.status_code == 201, created.text
    fetched = await client.get("/api/rooms/marc")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Marc"


@pytest.mark.asyncio
async def test_making_a_room_under_another_spelling_gives_the_one_there(client) -> None:
    await client.post("/api/rooms", json={"name": "Marc"})
    again = await client.post("/api/rooms", json={"name": "mARC"})
    assert again.json()["name"] == "Marc"
    rooms = sorted(p.name for p in (get_data_dir() / "rooms").iterdir() if p.is_dir())
    assert [r for r in rooms if r.casefold() == "marc"] == ["Marc"]


def test_a_pattern_cannot_claim_another_spelling_of_a_room() -> None:
    get_room_dir("Marc")
    with pytest.raises(HTTPException) as refused:
        patterns_route._claim_room("marc", exact=True)
    assert refused.value.status_code == 409
    assert patterns_route._claim_room("marc", exact=False) == "marc-2"
