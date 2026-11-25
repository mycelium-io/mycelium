# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room a hub recorded before 3.1 works as it is stored.

Before 3.1 a message's envelope sat under ``l9``, ids began ``urn:ioc:``, and
headers named their format ``SSTP``. Nothing rewrites that: an old task keeps
its old thread id, which matches itself, and the room's own channel is the
room in either form.
"""

from __future__ import annotations

import json

import pytest
import yaml
from httpx import AsyncClient

from app.routes import participate
from app.services import message_format, persister
from app.services.filesystem import get_room_dir, write_memory_file

ROOM = "older"
OLD_THREAD = f"urn:ioc:mycelium:episode:{ROOM}:4f2a9c1e"
OLD_LIVE = f"urn:ioc:mycelium:episode:{ROOM}:live"


def _old_record(message_id: str, episode: str, sender: str, text: str) -> dict:
    return {
        "message_id": message_id,
        "sender": sender,
        "kind": "exchange",
        "subkind": None,
        "recorded_at": "2026-10-01T12:00:00+00:00",
        "content": {
            "content": text,
            "l9": {
                "header": {
                    "protocol": "SSTP",
                    "subprotocol": "mycelium",
                    "version": "0.0.6",
                    "kind": "exchange",
                    "participants": {
                        "actors": [{"id": sender, "role": "agent"}],
                        "groups": None,
                    },
                    "message": {"id": message_id, "parents": [], "episode": episode},
                    "context": {"topic": f"urn:concept:mycelium:{ROOM}"},
                },
                "payload": {"type": "message", "data": {}},
            },
        },
    }


@pytest.fixture
async def old_room(client: AsyncClient) -> None:
    assert (await client.post("/api/rooms", json={"name": ROOM})).status_code in (200, 201)
    room = get_room_dir(ROOM)
    for handle in ("juno", "coder"):
        write_memory_file(
            room,
            f"agents/{handle}",
            yaml.safe_dump({"adapter": "claude_code", "owner": "julia"}),
            created_by="julia",
        )
    (room / "work").mkdir(exist_ok=True)
    (room / "work" / "ship-it.md").write_text(
        f"---\nepisode: {OLD_THREAD}\ntype: work\n---\nShip it\n", encoding="utf-8"
    )
    (room / "log").mkdir(exist_ok=True)
    lines = [
        _old_record("m-room", OLD_LIVE, "juno", "morning, room"),
        _old_record("m-thread", OLD_THREAD, "juno", "starting on it"),
    ]
    (room / "log" / "transcript.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8"
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("old_room")
async def test_an_old_thread_keeps_its_id_and_its_messages(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(participate, "_MAX_WAIT_S", 0.005)

    # The old thread's messages read by the id the row carries.
    read = await client.get(f"/api/rooms/{ROOM}/messages", params={"episode": OLD_THREAD})
    assert [m["content"] for m in read.json()["messages"]] == ["starting on it"]

    # Juno is reading the thread (its first await starts at the end of it).
    first = await client.get(
        f"/api/rooms/{ROOM}/await", params={"handle": "juno", "episode": OLD_THREAD}
    )
    assert first.status_code == 200, first.text

    # A reply into it lands under that same id, beside the old message.
    replied = await client.post(
        f"/api/rooms/{ROOM}/reply",
        json={"handle": "coder", "text": "@juno done", "episode": OLD_THREAD},
    )
    assert replied.status_code == 200, replied.text
    thread = [r for r in persister.load_transcript(ROOM) if r.sender == "coder"]
    assert [persister.record_episode(r) for r in thread] == [OLD_THREAD]
    read = await client.get(f"/api/rooms/{ROOM}/messages", params={"episode": OLD_THREAD})
    assert {m["content"] for m in read.json()["messages"]} == {"starting on it", "@juno done"}

    # And it is handed to the agent it asks, scoped to that thread.
    turn = await client.get(
        f"/api/rooms/{ROOM}/await", params={"handle": "juno", "episode": OLD_THREAD}
    )
    assert turn.json()["prompt"] == "@juno done"


@pytest.mark.asyncio
@pytest.mark.usefixtures("old_room")
async def test_the_rooms_own_channel_is_the_room_in_either_form(client: AsyncClient):
    assert message_format.is_live_episode(ROOM, OLD_LIVE)
    assert message_format.is_live_episode(ROOM, message_format.live_episode_urn(ROOM))
    sent = await client.post(
        f"/api/rooms/{ROOM}/messages",
        json={"sender_handle": "julia", "message_type": "broadcast", "content": "hello again"},
    )
    assert sent.status_code == 201, sent.text
    room_messages = [
        m["content"]
        for m in (await client.get(f"/api/rooms/{ROOM}/messages")).json()["messages"]
        if message_format.is_live_episode(ROOM, m.get("episode"))
    ]
    assert {"morning, room", "hello again"} <= set(room_messages)


def test_an_old_envelope_reads_under_either_key():
    old = _old_record("m-1", OLD_THREAD, "juno", "hi")["content"]
    assert message_format.envelope_of(old)["header"]["protocol"] == "SSTP"
    assert message_format.same_episode(OLD_THREAD, f"urn:mycelium:episode:{ROOM}:4f2a9c1e")
    assert not message_format.same_episode(OLD_THREAD, f"urn:mycelium:episode:{ROOM}:other")
