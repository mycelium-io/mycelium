# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The wake bugs found so far, replayed through the real routes.

Each is a short sequence of what agents and people did, written the way they
write it (``wake_paths``), then read back the way a runner and an agent read
it: the wakes handed over, what each one's digest covered, and what ``await``
hands the agent next.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.services import room_channels, wake_log
from tests import wake_paths
from tests.wake_paths import AGENT, PEER, PERSON, ROOM


@pytest_asyncio.fixture
async def room(client, monkeypatch) -> wake_paths.Room:
    room = await wake_paths.open_room(client, monkeypatch)
    for handle in (AGENT, PEER):
        wake_paths.mark_read(room, handle)
    return room


def _busy(*handles: str) -> None:
    states = dict.fromkeys(wake_paths.HERDR, "idle") | dict.fromkeys(handles, "working")
    room_channels.manager.set_herdr_presence(ROOM, states)


def _last_id(room: wake_paths.Room, sender: str) -> str:
    return next(r.message_id for r in reversed(room.log.records) if r.sender == sender)


@pytest.mark.asyncio
async def test_a_wake_held_while_busy_keeps_the_mention_its_agent_posted_past(room):
    # The planner asks the coder while it's busy; the coder posts its own reply
    # a second later without having read the ask; then it goes idle.
    _busy(AGENT)
    await wake_paths.say(room, PEER, "Two parts left. @coder can you take the parser?")
    asked = _last_id(room, PEER)
    await wake_paths.say(room, AGENT, "Here's the summary you asked for.")
    assert await wake_paths.handed(room) == []  # held while it works
    _busy()

    (wake,) = await wake_paths.handed(room)
    assert (wake["reason"], wake["from"]) == ("mention", PEER)
    assert "@coder can you take the parser?" in wake["prompt"]
    (entry,) = wake_log.read(ROOM, agent=AGENT, limit=1)
    assert entry["messages"] == [asked]
    assert (await wake_paths.await_turn(AGENT))["message_id"] == asked


@pytest.mark.asyncio
async def test_a_reply_does_not_ask_whoever_its_sender_last_heard_from(room):
    # The coder is handed the planner's ask, then answers the person instead.
    # ``respond`` names the planner as that reply's recipient.
    await wake_paths.say(room, PEER, "@coder can you look at the parser?")
    assert (await wake_paths.await_turn(AGENT))["sender"] == PEER
    room_channels.manager._herdr_wakes.clear()
    await wake_paths.say(room, AGENT, "Yes, that command works.", to=(PEER,))

    reply = room.log.records[-1]
    assert reply.sender == AGENT
    assert PEER in [a["id"] for a in reply.content["l9"]["header"]["participants"]["actors"]]
    got = await wake_paths.decided(room, PEER)
    assert got == wake_paths.Decided(doorbell=None, awaited=False, digest=False)


@pytest.mark.asyncio
async def test_an_interrupt_keeps_its_sender_when_a_lesser_mention_follows(room):
    _busy(AGENT)
    await wake_paths.say(room, PERSON, "@!coder stop, that's main")
    await wake_paths.say(room, PEER, "@coder also, the parser")
    _busy()

    (wake,) = await wake_paths.handed(room)
    assert (wake["reason"], wake["from"]) == ("interrupt", PERSON)
    (entry,) = wake_log.read(ROOM, agent=AGENT, limit=1)
    assert len(entry["messages"]) == 2  # both asks are in its digest


@pytest.mark.asyncio
async def test_a_wake_whose_message_was_read_before_it_was_due_is_skipped(room):
    _busy(AGENT)
    await wake_paths.say(room, PERSON, "@coder can you look?")
    # The agent's own loop reads it while the wake is held.
    assert (await wake_paths.await_turn(AGENT))["sender"] == PERSON
    _busy()

    assert await wake_paths.handed(room) == []
    (entry,) = wake_log.read(ROOM, agent=AGENT, limit=1)
    assert (entry["outcome"], entry["reason"]) == ("skipped", "mention")


@pytest.mark.asyncio
async def test_a_restart_between_the_mention_and_the_handover_loses_nothing(room):
    # The queued wake is the hub's memory and goes with a restart; the read
    # cursor is on disk and doesn't, so the mention is still unread: the next
    # wake's digest lists it and ``await`` hands it over.
    _busy(AGENT)
    await wake_paths.say(room, PERSON, "@coder can you look at the parser?")
    asked = _last_id(room, PERSON)
    wake_paths.restart(room)
    _busy()
    assert await wake_paths.handed(room) == []

    room_channels.manager.enqueue_herdr_wake(ROOM, AGENT, reason="assigned", key="work/x")
    (wake,) = await wake_paths.handed(room)
    assert "can you look at the parser?" in wake["prompt"]
    (entry,) = wake_log.read(ROOM, agent=AGENT, limit=1)
    assert entry["messages"] == [asked]
    assert (await wake_paths.await_turn(AGENT))["message_id"] == asked
