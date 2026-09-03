# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Board-first creation over HTTP: ``POST /rooms/{room}/tasks``.

Creating a task is the one write that mints a thread, and minting is a
capability of this route rather than a field a caller supplies — the binding has
no wire form anywhere else on purpose. So what these hold is that the route
mints, that a decomposition is recorded as a real ontology edge or refused, and
that the assignment it writes stays an assignment rather than becoming custody
nobody took.
"""

from __future__ import annotations

import pytest

from app.routes.tasks import PARENT_RELATION
from app.services import tasks
from app.services.filesystem import EPISODE_META, get_room_dir, read_memory_file

ROOM = "atlas"


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


async def _room(client) -> str:
    assert (await client.post("/api/rooms", json={"name": ROOM})).status_code in (200, 201)
    return ROOM


async def _new(client, title: str, **body):
    return await client.post(
        f"/api/rooms/{ROOM}/tasks", json={"title": title, "handle": "julia", **body}
    )


@pytest.mark.asyncio
async def test_a_created_unit_comes_with_its_thread(client):
    await _room(client)
    resp = await _new(client, "Ship passkey login")
    assert resp.status_code == 201
    task = resp.json()
    assert task["key"] == "work/ship-passkey-login"
    assert task["episode"].startswith(f"urn:ioc:mycelium:episode:{ROOM}:")
    # On the row itself, not only in the answer: the board reads the file.
    found = read_memory_file(get_room_dir(ROOM), task["key"])
    assert found is not None
    assert found[0][EPISODE_META] == task["episode"]


@pytest.mark.asyncio
async def test_the_thread_is_the_room_s_own_and_the_store_knows_it(client):
    await _room(client)
    task = (await _new(client, "Rotate the signing key")).json()
    # What tells a task's thread from an orphaned episode, and what the write
    # guard in leg 2 recognises a nameable thread by.
    assert task["episode"] in tasks.bound_episodes(ROOM)
    assert tasks.episode_of(ROOM, task["key"]) == task["episode"]


@pytest.mark.asyncio
async def test_a_unit_lands_on_the_board_as_an_open_action(client):
    await _room(client)
    task = (await _new(client, "Draft the migration")).json()
    assert task["meta"]["kind"] == tasks.TASK_KIND
    assert task["meta"]["status"] == "open"


@pytest.mark.asyncio
async def test_an_assignment_is_not_a_claim(client):
    """Who a task is *for* is a field; who holds it is a lease nobody has taken."""
    await _room(client)
    task = (await _new(client, "Wire the callback", assignee="@sec")).json()
    assert task["meta"][tasks.ASSIGNEE_FIELD] == "sec"
    assert "custody" not in task["meta"]
    assert "owner" not in task["meta"]


@pytest.mark.asyncio
async def test_a_child_unit_records_a_real_relation_to_its_parent(client):
    await _room(client)
    parent = (await _new(client, "Ship passkey login")).json()
    child = (await _new(client, "Pick token storage", parent=parent["key"])).json()
    assert child["meta"][PARENT_RELATION] == parent["key"]
    # Its own thread, not the parent's: decomposing opens a new conversation.
    assert child["episode"] != parent["episode"]


@pytest.mark.asyncio
async def test_a_parent_the_room_does_not_have_is_refused(client):
    """Rather than written: a dangling edge reads as a top-level task forever."""
    await _room(client)
    resp = await _new(client, "Pick token storage", parent="work/nothing-here")
    assert resp.status_code == 404
    assert read_memory_file(get_room_dir(ROOM), "work/pick-token-storage") is None


@pytest.mark.asyncio
async def test_a_room_that_does_not_exist_is_a_404_not_a_new_room(client):
    resp = await client.post(
        "/api/rooms/nowhere/tasks", json={"title": "Ship it", "handle": "julia"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_second_unit_with_the_same_title_keeps_the_first_one_s_thread(client):
    """The key is deterministic, so this is an upsert — and a binding is write-once."""
    await _room(client)
    first = (await _new(client, "Ship passkey login")).json()
    again = (await _new(client, "Ship passkey login")).json()
    assert again["key"] == first["key"]
    assert again["episode"] == first["episode"]
