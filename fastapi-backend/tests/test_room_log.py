# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room is its log on the hub, and needs nothing else running to work.

A person's message to a room the hub has just made goes through the real send
route, lands in the room's transcript on disk, and is what a mentioned agent's
``await`` hands it: no node, no channel set up first, nothing faked between
the two routes.
"""

from __future__ import annotations

import pytest
import yaml
from httpx import AsyncClient

from app.routes import participate
from app.services import persister
from app.services.filesystem import get_room_dir, write_memory_file

ROOM = "fresh-room"


@pytest.mark.asyncio
async def test_a_persons_message_is_recorded_and_handed_to_the_agent_it_mentions(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    # ``await`` with no timeout waits its longest; one poll is enough here.
    monkeypatch.setattr(participate, "_MAX_WAIT_S", 0.005)
    assert (await client.post("/api/rooms", json={"name": ROOM})).status_code in (200, 201)
    write_memory_file(
        get_room_dir(ROOM),
        "agents/coder",
        yaml.safe_dump({"adapter": "claude_code", "owner": "julia"}),
        created_by="julia",
    )

    sent = await client.post(
        f"/api/rooms/{ROOM}/messages",
        json={"sender_handle": "julia", "message_type": "broadcast", "content": "@coder hi"},
    )
    assert sent.status_code == 201, sent.text

    (said,) = [r for r in persister.load_transcript(ROOM) if r.sender == "julia"]
    assert said.content["content"] == "@coder hi"

    turn = await client.get(f"/api/rooms/{ROOM}/await", params={"handle": "coder"})
    assert turn.status_code == 200, turn.text
    body = turn.json()
    assert (body["sender"], body["prompt"]) == ("julia", "@coder hi")
    assert body["message_id"] == said.message_id

    # Handed once: the next ``await`` has nothing new.
    again = await client.get(f"/api/rooms/{ROOM}/await", params={"handle": "coder", "timeout": 0})
    assert again.json()["message"] is None
