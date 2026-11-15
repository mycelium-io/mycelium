# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent's subagents: a handle of their own, recorded with their parent.

A subagent is ``<parent>:<name>``, started as its parent and recorded in the
room, so only a recorded one posts and its parent's token is the only one that
may act as it. It ends on ``subagent end``, when its step ends in the parent's
session file (as the runner counts it), when its parent stops, or on a timeout.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.services import subagents
from app.services.filesystem import room_path, write_memory_file

ROOM = "checkout"


@pytest.fixture(autouse=True)
def _fresh_counts() -> None:
    subagents._last_finished.clear()


@pytest.fixture
async def room(client: AsyncClient) -> AsyncClient:
    await client.post("/api/rooms", json={"name": ROOM})
    return client


async def start(client: AsyncClient, name: str = "review", parent: str = "builder", **kw: Any):
    return await client.post(
        f"/api/rooms/{ROOM}/subagents", json={"name": name, "parent": parent}, **kw
    )


async def post(client: AsyncClient, sender: str, **kw: Any):
    return await client.post(
        f"/api/rooms/{ROOM}/messages",
        json={"sender_handle": sender, "message_type": "broadcast", "content": "refund tests pass"},
        **kw,
    )


def state(handle: str) -> str | None:
    found = subagents.record(ROOM, handle)
    return found["state"] if found else None


async def test_a_started_subagent_has_its_own_handle_and_posts_as_it(room):
    started = await start(room)
    assert started.status_code == 201, started.text
    assert started.json() == {**started.json(), "handle": "builder:review", "parent": "builder"}
    sent = await post(room, "builder:review")
    assert sent.status_code == 201, sent.text
    assert sent.json()["sender_handle"] == "builder:review"
    listed = (await room.get(f"/api/rooms/{ROOM}/subagents")).json()
    assert [(s["handle"], s["state"]) for s in listed] == [("builder:review", "working")]


async def test_nobody_posts_as_a_subagent_that_wasn_t_started(room):
    refused = await post(room, "builder:made-up")
    assert refused.status_code == 403
    assert "subagent start" in refused.json()["detail"]


async def test_an_ended_subagent_is_kept_but_posts_no_more(room):
    await start(room)
    ended = await room.delete(f"/api/rooms/{ROOM}/subagents/builder:review")
    assert ended.status_code == 200, ended.text
    assert ended.json()["state"] == "ended"
    assert (await post(room, "builder:review")).status_code == 403
    listed = (await room.get(f"/api/rooms/{ROOM}/subagents")).json()
    assert [s["state"] for s in listed] == ["ended"], "kept, so its messages still read as its"


async def test_a_subagent_replies_as_an_agent_does(room):
    # `mycelium respond` posts through /reply, which takes only a registered
    # handle: a running subagent counts, an unstarted or ended one doesn't.
    async def reply() -> int:
        body = {"handle": "builder:review", "text": "the retry path is covered"}
        return (await room.post(f"/api/rooms/{ROOM}/reply", json=body)).status_code

    assert await reply() == 403
    await start(room)
    # Past the guard; with no live channel in tests the route then answers 503.
    assert await reply() != 403
    await room.delete(f"/api/rooms/{ROOM}/subagents/builder:review")
    assert await reply() == 403


@pytest.mark.parametrize(
    ("name", "parent", "status"),
    [
        ("Review Bot", "builder", 422),
        ("re:view", "builder", 422),
        # A subagent's subagent: its parent isn't a recorded subagent here.
        ("review", "builder:other", 403),
    ],
)
async def test_a_subagent_s_name_and_parent_are_checked(room, name: str, parent: str, status: int):
    assert (await start(room, name=name, parent=parent)).status_code == status


async def test_no_agent_is_named_like_a_subagent(room):
    item = {"key": "agents/builder:review", "value": "adapter: claude_code", "created_by": "x"}
    resp = await room.post(f"/api/rooms/{ROOM}/memory", json={"items": [item]})
    assert resp.status_code == 422
    assert "colon" in resp.json()["detail"]


async def test_a_parent_s_token_acts_as_its_recorded_subagents_and_nobody_else_s(
    client, signed_in_hub
):
    me = signed_in_hub.headers("builder")
    await client.post("/api/rooms", json={"name": ROOM}, headers=me)
    assert (await start(client, headers=me)).status_code == 201

    assert (await post(client, "builder:review", headers=me)).status_code == 201
    # Not one it didn't start, and not someone else's.
    assert (await post(client, "builder:other", headers=me)).status_code == 403
    others = signed_in_hub.headers("scout")
    assert (await post(client, "builder:review", headers=others)).status_code == 403
    # Nor can someone else start one under another's name.
    assert (await start(client, name="spy", headers=others)).status_code == 403


def test_a_step_ending_in_the_parent_s_session_ends_its_subagent(room, monkeypatch):
    subagents.start(ROOM, "builder", "review")
    # Started, but the parent hasn't called it yet: nothing open, nothing ends.
    subagents.observe(ROOM, "builder", 0, "working")
    assert state("builder:review") == "working"
    subagents.observe(ROOM, "builder", 1, "working")
    subagents.observe(ROOM, "builder", 0, "working")
    assert state("builder:review") == "done", "faded, still listed"
    monkeypatch.setattr(subagents, "DONE_FOR", timedelta(0))
    assert state("builder:review") == "ended"


def test_a_cli_whose_session_isn_t_read_leaves_it_to_the_other_ways(room):
    subagents.start(ROOM, "builder", "review")
    subagents.observe(ROOM, "builder", None, "working")
    assert state("builder:review") == "working"


@pytest.mark.parametrize("parent_state", ["stopped", "gone"])
def test_its_parent_stopping_ends_it(room, parent_state: str):
    subagents.start(ROOM, "builder", "review")
    subagents.observe(ROOM, "builder", None, parent_state)
    assert state("builder:review") == "ended"


def test_one_nobody_reports_on_ends_after_a_while(room, monkeypatch):
    subagents.start(ROOM, "builder", "review")
    monkeypatch.setattr(subagents, "TIMEOUT", timedelta(0))
    assert state("builder:review") == "ended"


async def test_the_runner_s_heartbeat_carries_the_count(room):
    subagents.start(ROOM, "builder", "review")

    def hello(open_steps: int) -> dict:
        agent = {
            "handle": "builder",
            "room": ROOM,
            "pane": "w1:p1",
            "state": "working",
            "subagents_open": open_steps,
        }
        return {
            "id": "mac",
            "label": "A Mac",
            "machine": {
                "machine": "mac",
                "workspaces": [{"id": "w1", "label": "checkout", "agents": [agent]}],
            },
        }

    for count in (1, 0):
        resp = await room.post("/api/runners", json=hello(count))
        assert resp.status_code == 200, resp.text
    assert state("builder:review") == "done"


def test_a_step_that_finished_between_two_heartbeats_still_ends_it(room):
    # The parent's runner has counted 3 finished steps before this one starts.
    subagents.observe(ROOM, "builder", 0, "working", finished_steps=3)
    subagents.start(ROOM, "builder", "review")
    # The step opened and closed before the next heartbeat: never seen open.
    subagents.observe(ROOM, "builder", 0, "working", finished_steps=4)
    assert state("builder:review") == "done"


def test_finished_steps_end_subagents_oldest_first(room):
    subagents.observe(ROOM, "builder", 0, "working", finished_steps=0)
    subagents.start(ROOM, "builder", "review")
    subagents.start(ROOM, "builder", "tests")
    subagents.observe(ROOM, "builder", 1, "working", finished_steps=1)
    assert (state("builder:review"), state("builder:tests")) == ("done", "working")
    subagents.observe(ROOM, "builder", 1, "working", finished_steps=1)
    assert state("builder:tests") == "working", "one step ends one subagent, once"
    subagents.observe(ROOM, "builder", 0, "working", finished_steps=2)
    assert state("builder:tests") == "done"


def test_a_runner_that_started_again_counts_from_its_new_number(room):
    subagents.observe(ROOM, "builder", 0, "working", finished_steps=9)
    subagents.start(ROOM, "builder", "review")
    subagents.observe(ROOM, "builder", 0, "working", finished_steps=0)
    assert state("builder:review") == "working"
    subagents.observe(ROOM, "builder", 0, "working", finished_steps=1)
    assert state("builder:review") == "done"


async def claimed_by_subagent(client: AsyncClient) -> str:
    """A row on the board, claimed by ``builder:review``."""
    key = "work/add-refund-tests"
    write_memory_file(room_path(ROOM), key, "# Add refund tests", created_by="operator")
    await start(client)
    claimed = await client.post(
        f"/api/rooms/{ROOM}/assignments/claim", json={"key": key, "handle": "builder:review"}
    )
    assert claimed.status_code == 200, claimed.text
    assert (claimed.json()["assignment"], claimed.json()["owner"]) == ("held", "builder:review")
    return key


async def test_a_row_a_subagent_claimed_goes_back_when_it_ends(room):
    key = await claimed_by_subagent(room)
    assert (await room.delete(f"/api/rooms/{ROOM}/subagents/builder:review")).status_code == 200
    row = (await room.get(f"/api/rooms/{ROOM}/assignments/{key}")).json()
    assert (row["assignment"], row["owner"]) == ("released", None), row
    assert "builder:review ended" in str(row)


async def test_a_row_held_by_a_subagent_that_timed_out_goes_back_on_the_next_read(
    room, monkeypatch
):
    key = await claimed_by_subagent(room)
    monkeypatch.setattr(subagents, "TIMEOUT", timedelta(0))
    await room.get(f"/api/rooms/{ROOM}/subagents")
    row = (await room.get(f"/api/rooms/{ROOM}/assignments/{key}")).json()
    assert row["assignment"] == "released", row
