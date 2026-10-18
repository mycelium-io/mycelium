# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A subscription wakes its agent through the paths that already exist.

Written the way agents and people write (``wake_paths``) and read back the way
a runner and an agent read it: the routes that subscribe, the doorbell's wake
and its digest, ``await``'s turn, and the member card.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.services import room_channels, subscriptions, wake_log
from tests import wake_paths
from tests.wake_paths import AGENT, PEER, PERSON, ROOM

TASK = "work/parser-work"


@pytest_asyncio.fixture
async def room(client, monkeypatch) -> wake_paths.Room:
    subscriptions.reset()
    room = await wake_paths.open_room(client, monkeypatch)
    for handle in (AGENT, PEER):
        wake_paths.mark_read(room, handle)
    return room


def _said_last(room: wake_paths.Room) -> str:
    """The newest message with text: a thread post is followed by its ping."""
    return next(r.message_id for r in reversed(room.log.records) if r.content.get("content"))


async def _subscribe(room: wake_paths.Room, handle: str = AGENT, **body) -> dict:
    response = await room.client.post(
        f"/api/rooms/{ROOM}/subscriptions", json={"handle": handle, **body}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_subscribing_listing_and_dropping_through_the_api(room):
    sub = await _subscribe(room, kind="task", target=TASK, parts=True)
    assert sub["describe"] == f"{TASK} and its parts"
    member = await _subscribe(room, kind="member", target=PEER, span="3d")
    assert member["until"] is not None
    listed = (await room.client.get(f"/api/rooms/{ROOM}/subscriptions?handle={AGENT}")).json()
    assert {s["id"] for s in listed["subscriptions"]} == {sub["id"], member["id"]}
    # On the member card too.
    card = (await room.client.get(f"/api/rooms/{ROOM}/sessions/members")).json()
    assert {s["id"] for s in card["subscriptions"]} == {sub["id"], member["id"]}

    gone = await room.client.delete(
        f"/api/rooms/{ROOM}/subscriptions", params={"handle": AGENT, "id": sub["id"]}
    )
    assert [s["id"] for s in gone.json()["removed"]] == [sub["id"]]
    gone = await room.client.delete(f"/api/rooms/{ROOM}/subscriptions", params={"handle": AGENT})
    assert [s["id"] for s in gone.json()["removed"]] == [member["id"]]


@pytest.mark.asyncio
async def test_what_cant_be_subscribed_to_is_refused_by_the_api(room):
    for body, status in (
        ({"kind": "task", "target": "work/nope"}, 404),
        ({"kind": "notice", "target": "merged"}, 422),
        ({"kind": "member", "target": PEER, "span": "soon"}, 422),
    ):
        response = await room.client.post(
            f"/api/rooms/{ROOM}/subscriptions", json={"handle": AGENT, **body}
        )
        assert response.status_code == status, response.text


@pytest.mark.asyncio
async def test_a_post_in_a_subscribed_task_rings_says_why_and_is_awaited(room):
    await _subscribe(room, kind="task", target=TASK)
    await wake_paths.say(room, PERSON, "the parser is green now", where="thread")
    posted = _said_last(room)

    (wake,) = await wake_paths.handed(room)
    assert wake["reason"] == "subscribed"
    assert f"Why:     you subscribed to {TASK}: @{PERSON} posted in it" in wake["prompt"]
    assert f"Watching: {TASK}: @{PERSON} posted in it" in wake["prompt"]
    # The reply goes where it was said.
    assert f"--task {TASK}" in wake["prompt"]
    (entry,) = wake_log.read(ROOM, agent=AGENT, limit=1)
    assert entry["watching"] == [posted]

    turn = await wake_paths.await_turn(AGENT)
    assert turn["message_id"] == posted
    assert turn["reason"] == "subscribed"
    assert turn["why"] == f"you subscribed to {TASK}: @{PERSON} posted in it"
    assert turn["asks"] == []
    assert [w["message_id"] for w in turn["watching"]] == [posted]


@pytest.mark.asyncio
async def test_a_mention_outranks_a_subscription_and_both_are_handed_over(room):
    await _subscribe(room, kind="task", target=TASK)
    await wake_paths.say(room, PERSON, "the parser is green now", where="thread")
    watched = _said_last(room)
    await wake_paths.say(room, PERSON, "@coder can you ship it?")
    asked = _said_last(room)
    # A later subscribed event doesn't take the mention's place either.
    await wake_paths.say(room, PERSON, "and the docs too", where="thread")

    (wake,) = await wake_paths.handed(room)
    assert wake["reason"] == "mention"
    assert "Watching:" in wake["prompt"]
    turn = await wake_paths.await_turn(AGENT)
    assert (turn["message_id"], turn["reason"]) == (asked, "mention")
    assert watched in [w["message_id"] for w in turn["watching"]]


@pytest.mark.asyncio
async def test_a_notice_wakes_only_whoever_subscribed_to_it(room):
    await _subscribe(room, kind="notice", target="claimed")
    await room_channels.manager.raise_notice(
        ROOM, subkind="claimed", key=TASK, title="Parser work", by=PERSON
    )
    (wake,) = await wake_paths.handed(room)
    assert (wake["handle"], wake["reason"]) == (AGENT, "subscribed")
    assert "claimed" in wake["prompt"]
    assert (await wake_paths.await_turn(PEER)).get("message_id") is None


@pytest.mark.asyncio
async def test_a_subscribed_wake_with_nothing_unread_is_skipped(room):
    await _subscribe(room, kind="member", target=PEER)
    await wake_paths.say(room, PEER, "pushed the fix")
    # The agent reads it before the wake is due.
    await wake_paths.await_turn(AGENT)
    assert await wake_paths.handed(room) == []
    (entry,) = wake_log.read(ROOM, agent=AGENT, limit=1)
    assert entry["outcome"] == "skipped"


@pytest.mark.asyncio
async def test_an_answer_to_the_agent_never_wakes_it_through_a_subscription(room):
    await _subscribe(room, kind="member", target=PEER)
    await wake_paths.say(room, PEER, "Yes, that command works.", to=(AGENT,))
    assert await wake_paths.handed(room) == []
    assert (await wake_paths.await_turn(AGENT)).get("message_id") is None


async def _board_send(room: wake_paths.Room, sender: str, text: str) -> None:
    """``mycelium board send``: a plain message in the task's thread, with no
    recipient, through the same route the app posts with."""
    body = {"sender_handle": sender, "message_type": "broadcast", "content": text}
    response = await room.client.post(
        f"/api/rooms/{ROOM}/messages", json={**body, "episode": room.thread}
    )
    assert response.status_code in (200, 201), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["board send", "respond"])
async def test_two_agents_subscribed_to_one_task_do_not_wake_each_other_forever(room, door):
    for handle in (AGENT, PEER):
        await _subscribe(room, handle=handle, kind="task", target=TASK)
        await _subscribe(
            room, handle=handle, kind="member", target=AGENT if handle == PEER else PEER
        )
    # The planner starts something in the task: the coder is woken, once.
    await _board_send(room, PEER, "who takes the docs?")
    (wake,) = await wake_paths.handed(room)
    assert (wake["handle"], wake["reason"]) == (AGENT, "subscribed")
    assert (await wake_paths.await_turn(AGENT))["reason"] == "subscribed"

    # The coder answers, by either door: the planner isn't woken for it.
    if door == "board send":
        await _board_send(room, AGENT, "I'll take them")
    else:
        await wake_paths.say(room, AGENT, "I'll take them", where="thread")
    assert await wake_paths.handed(room) == []
    assert (await wake_paths.await_turn(PEER)).get("message_id") is None


@pytest.mark.asyncio
async def test_a_wake_delivered_by_the_doorbell_counts_as_answering_too(room):
    for handle in (AGENT, PEER):
        await _subscribe(room, handle=handle, kind="task", target=TASK)
    await _board_send(room, PEER, "who takes the docs?")
    (wake,) = await wake_paths.handed(room)  # typed into the coder's pane
    assert wake["handle"] == AGENT
    # It answers straight from the digest, without an ``await``.
    await _board_send(room, AGENT, "I'll take them")
    assert await wake_paths.handed(room) == []
