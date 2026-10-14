# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A wake says what woke the agent, and isn't rung for nothing.

The sequence that showed it: one agent mentions another while the second is
busy, so the wake is held; the second posts its own reply a second later,
without having read the mention; then the held wake is handed over. Counting
only what came after the agent's last post, the wake covered nothing and said
"mention" with no message behind it. These hold that what's new is counted
from what the agent has read, that a wake with nothing unread behind it is
skipped rather than rung, and that a wake keeps the sender of what caused it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from app.services import message_format, room_channels, wake_digest, wake_log
from app.services.persister import DeliveryLog, TranscriptRecord

ROOM = "wake-room"
AT = datetime(2026, 10, 14, 16, 42, 18, tzinfo=UTC)


def _said(n: int, sender: str, text: str, seconds: int) -> TranscriptRecord:
    return TranscriptRecord(
        message_id=f"m{n}",
        sender=sender,
        kind="exchange",
        subkind=None,
        content={
            "content": text,
            "l9": {
                "header": {
                    "kind": "exchange",
                    "message": {"episode": message_format.live_episode_urn(ROOM)},
                    "participants": {"actors": [{"id": sender}]},
                },
                "payload": {"type": "message"},
            },
        },
        recorded_at=(AT + timedelta(seconds=seconds)).isoformat(),
    )


#: A person asks the planner; the planner answers and names the coder; the coder,
#: busy with an earlier turn, posts its own reply a second later without reading it.
SEQUENCE = [
    _said(1, "hay", "planner, what's left on the parser work?", 0),
    _said(2, "planner", "Two parts left. @coder can you take the parser?", 24),
    _said(3, "coder", "Here's the summary you asked for.", 25),
]
#: The coder had read up to the person's message, and no further.
CODER_READ = 1


def test_whats_new_is_counted_from_what_the_agent_read():
    wake = {"handle": "coder", "reason": "mention", "from": "planner"}
    # From its last post, the mention it never read looks old: the empty wake.
    assert wake_digest.coverage(wake, SEQUENCE) == {"messages": []}
    # From what it read, the mention is what this wake is about.
    read = {**wake, wake_digest.READ_FROM: CODER_READ}
    assert wake_digest.coverage(read, SEQUENCE) == {"messages": ["m2"], "range": ["m2", "m2"]}
    digest = wake_digest.build(ROOM, read, SEQUENCE, now=AT + timedelta(seconds=31))
    assert "@coder can you take the parser?" in digest


@pytest.fixture
def handing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    """The hub's herdr-wakes route, with one queued wake and the sequence above."""
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    log = DeliveryLog(SEQUENCE, {"coder": CODER_READ})
    managed = SimpleNamespace(persister=SimpleNamespace(log=log))
    queued: list[dict] = []
    manager = room_channels.manager
    monkeypatch.setattr(manager, "get", lambda _room: managed)
    monkeypatch.setattr(manager, "drain_herdr_wakes", lambda _room, **_k: list(queued))
    yield SimpleNamespace(queued=queued, log=log)


async def _handed(client: AsyncClient) -> list[dict]:
    await client.post("/api/rooms", json={"name": ROOM})
    response = await client.get(f"/api/rooms/{ROOM}/sessions/herdr-wakes")
    assert response.status_code == 200
    return response.json()["wakes"]


@pytest.mark.asyncio
async def test_a_wake_with_nothing_unread_behind_it_is_skipped(handing, client: AsyncClient):
    # The coder has since read everything: the mention is answered, nothing asks.
    handing.log.advance("coder", len(SEQUENCE))
    handing.queued.append({"handle": "coder", "reason": "mention", "from": "planner", "id": "w1"})
    assert await _handed(client) == []
    (entry,) = wake_log.read(ROOM)
    assert (entry["outcome"], entry["reason"]) == ("skipped", "mention")
    assert "nothing unread" in entry["why"]


@pytest.mark.asyncio
async def test_a_wake_with_an_unread_ask_is_handed_with_it(handing, client: AsyncClient):
    handing.queued.append({"handle": "coder", "reason": "mention", "from": "planner", "id": "w2"})
    (wake,) = await _handed(client)
    assert "can you take the parser?" in wake["prompt"]
    # The read position is the hub's to use, not the runner's to carry.
    assert wake_digest.READ_FROM not in wake
    (entry,) = wake_log.read(ROOM)
    assert (entry["outcome"], entry["messages"]) == ("handed", ["m2"])


@pytest.mark.asyncio
async def test_a_task_given_to_the_agent_needs_no_message(handing, client: AsyncClient):
    handing.log.advance("coder", len(SEQUENCE))
    handing.queued.append(
        {"handle": "coder", "reason": "assigned", "key": "work/parser", "id": "w3"}
    )
    (wake,) = await _handed(client)
    assert "gave you a task" in wake["prompt"]


def test_a_held_wake_keeps_the_sender_of_what_caused_it(monkeypatch):
    manager = room_channels.manager
    monkeypatch.setattr(manager, "_herdr_wakes", {})
    manager.enqueue_herdr_wake(ROOM, "coder", reason="interrupt", sender="hay")
    manager.enqueue_herdr_wake(ROOM, "coder", reason="mention", sender="planner")
    (wake,) = manager._herdr_wakes[ROOM]
    assert (wake["reason"], wake["from"]) == ("interrupt", "hay")
    # A cause of the same kind or higher does take over.
    manager.enqueue_herdr_wake(ROOM, "coder", reason="interrupt", sender="planner")
    assert manager._herdr_wakes[ROOM][0]["from"] == "planner"


def test_a_handback_says_so_rather_than_mention():
    wake = {
        "handle": "builder",
        "reason": "handback",
        "from": "reviewer",
        "key": "work/parser",
        wake_digest.READ_FROM: len(SEQUENCE),
    }
    digest = wake_digest.build(ROOM, wake, SEQUENCE, now=AT + timedelta(minutes=1))
    assert "@reviewer handed your task back to you in its thread" in digest
    assert "mycelium board messages work/parser" in digest
