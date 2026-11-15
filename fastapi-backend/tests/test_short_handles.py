# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A signed-in person gets a short handle, and their email is only how they sign in.

Real tokens through the real gate (``signed_in_hub``), with made-up addresses.
The first sign-in binds the person to the part of their claim before the ``@``
(or one they pick), and moves what the hub kept under the old handle, once,
recorded in the migrations ledger.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml
from httpx import AsyncClient

from app.routes.memory import upsert_memories
from app.schemas import MemoryBatchCreate, MemoryCreate
from app.services import (
    fields,
    migrations,
    principals,
    room_people,
    short_handles,
    subscriptions,
)
from app.services.filesystem import (
    get_data_dir,
    read_memory_file,
    read_room_meta,
    room_path,
    write_room_meta,
)

AVERY = "avery.quinn@example.com"
ROOM = "checkout"
#: Someone already on the hub, whose sign-in says a plain handle.
OPERATOR = "operator"


@pytest.fixture(autouse=True)
def _fresh_ledger():
    migrations.forget_seen()
    short_handles._failed_until.clear()
    yield
    migrations.forget_seen()
    short_handles._failed_until.clear()


async def whoami(client: AsyncClient, hub: Any, claim: str, **kw: Any) -> dict:
    resp = await client.get("/api/whoami", headers=hub.headers(claim, **kw))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def seed(key: str, value: str, **meta: Any) -> None:
    """As it was before short handles, written by the hub itself."""
    item = MemoryCreate(key=key, value=value, created_by="seed", embed=False, meta=meta or None)
    await upsert_memories(ROOM, MemoryBatchCreate(items=[item]))


def stored(key: str) -> tuple[dict, str]:
    found = read_memory_file(room_path(ROOM), key)
    assert found is not None
    return found


def ledger() -> list[dict]:
    return migrations.applied()


async def make_room(client: AsyncClient, hub: Any) -> None:
    await client.post("/api/rooms", json={"name": ROOM}, headers=hub.headers(OPERATOR))


async def test_a_plain_claim_is_the_handle_as_it_was(client, signed_in_hub):
    me = await whoami(client, signed_in_hub, OPERATOR)
    assert me["handle"] == OPERATOR
    assert me["needs_handle"] is False
    assert ledger() == []


async def test_an_email_claim_gives_the_short_handle_and_the_email_shows_nowhere(
    client, signed_in_hub
):
    me = await whoami(client, signed_in_hub, AVERY)
    assert me["handle"] == "avery.quinn"
    assert "@" not in json.dumps(me)
    # The same sign-in, later, is the same person.
    assert (await whoami(client, signed_in_hub, AVERY))["handle"] == "avery.quinn"


async def test_a_taken_short_handle_is_picked_before_anything_else(client, signed_in_hub):
    assert (await whoami(client, signed_in_hub, AVERY))["handle"] == "avery.quinn"
    other = "avery.quinn@other.example"
    me = await whoami(client, signed_in_hub, other)
    assert me == {**me, "needs_handle": True, "handle": None, "suggested": "avery.quinn"}

    refused = await client.get("/api/rooms", headers=signed_in_hub.headers(other))
    assert refused.status_code == 409
    assert refused.json()["detail"]["error"] == "auth.handle_needed"

    pick = "/api/whoami/handle"
    taken = await client.post(
        pick, json={"handle": "avery.quinn"}, headers=signed_in_hub.headers(other)
    )
    assert taken.status_code == 409
    bad = await client.post(pick, json={"handle": "a@b"}, headers=signed_in_hub.headers(other))
    assert bad.status_code == 422
    ok = await client.post(pick, json={"handle": "aquinn"}, headers=signed_in_hub.headers(other))
    assert ok.status_code == 200, ok.text
    assert ok.json()["handle"] == "aquinn"
    assert (await client.get("/api/rooms", headers=signed_in_hub.headers(other))).status_code == 200


async def test_an_agent_s_handle_is_taken(client, signed_in_hub):
    await make_room(client, signed_in_hub)
    await seed("agents/scout", "adapter: claude_code")
    me = await whoami(client, signed_in_hub, "scout@example.com")
    assert me["needs_handle"] is True


async def test_a_plain_handle_with_rights_isn_t_handed_to_someone_else(client, signed_in_hub):
    """Sam signs in as plain `sam`, owns an agent, has no user record and
    hasn't signed in since the update. Someone signing in as
    `sam@other.example` mustn't get `sam`, and with it Sam's agent."""
    await make_room(client, signed_in_hub)
    await seed("agents/sams-helper", "adapter: claude_code\nowner: sam")
    me = await whoami(client, signed_in_hub, "sam@other.example")
    assert me["needs_handle"] is True
    # Sam's own sign-in is still Sam.
    assert (await whoami(client, signed_in_hub, "sam"))["handle"] == "sam"


@pytest.mark.parametrize(
    "where",
    ["allow_from", "members", "assignee"],
)
async def test_a_handle_named_anywhere_rights_live_is_taken(client, signed_in_hub, where: str):
    await make_room(client, signed_in_hub)
    if where == "allow_from":
        await seed("agents/helper", "adapter: claude_code\nallow_from: [sam]")
    elif where == "members":
        meta = read_room_meta(ROOM) or {}
        write_room_meta(ROOM, {**meta, "members": [*meta.get("members", []), "sam"]})
    else:
        await seed("work/ship-it", "Ship it", assignee="@sam")
    assert (await whoami(client, signed_in_hub, "sam@other.example"))["needs_handle"] is True


async def _old_room(hub: Any, client: AsyncClient) -> None:
    await make_room(client, hub)
    await seed(
        "agents/builder", f"adapter: claude_code\nowner: {AVERY}\nallow_from: [{AVERY}, {OPERATOR}]"
    )
    await seed("work/ship-it", "Ship it", assignee=f"@{AVERY}")
    principals.write_user({"handle": AVERY, "display_name": "Avery Quinn"})
    room_people.add(ROOM, AVERY, "added")
    await subscriptions.add(ROOM, AVERY, "member", "builder")
    folders = get_data_dir() / "preferences" / AVERY
    folders.mkdir(parents=True)
    (folders / "room-folders.json").write_text("{}")


async def test_the_first_sign_in_moves_everything_kept_under_the_old_handle(client, signed_in_hub):
    await _old_room(signed_in_hub, client)
    me = await whoami(client, signed_in_hub, AVERY)
    assert me["handle"] == "avery.quinn"

    builder = yaml.safe_load(stored("agents/builder")[1])
    assert builder["owner"] == "avery.quinn"
    assert builder["allow_from"] == ["avery.quinn", OPERATOR]
    assert stored("work/ship-it")[0]["assignee"] == "@avery.quinn"
    assert principals.load_user(AVERY) is None
    moved_user = principals.load_user("avery.quinn")
    assert moved_user is not None
    assert moved_user["display_name"] == "Avery Quinn"
    assert "avery.quinn" in room_people.handles(ROOM)
    assert AVERY not in room_people.handles(ROOM)
    assert [s.handle for s in subscriptions.load(ROOM)] == ["avery.quinn"]
    assert (get_data_dir() / "preferences" / "avery.quinn" / "room-folders.json").exists()
    # Past messages still carry the old handle; the app shows them under the name.
    user = await client.get("/api/users/avery.quinn", headers=signed_in_hub.headers(AVERY))
    assert user.json()["was"] == [AVERY]

    (entry,) = ledger()
    assert entry["id"] == short_handles.MIGRATION
    assert entry["changed"]["rooms"] == {ROOM: 4}
    # Once: a later request doesn't run it again.
    await whoami(client, signed_in_hub, AVERY)
    assert len(ledger()) == 1


async def test_a_move_stopped_partway_finishes_later_and_isn_t_rerun_on_every_request(
    client, signed_in_hub, monkeypatch: pytest.MonkeyPatch
):
    await _old_room(signed_in_hub, client)
    real = short_handles._move_room
    tries = 0

    async def crash(*_a: Any) -> int:
        nonlocal tries
        tries += 1
        raise RuntimeError("the hub stopped")

    monkeypatch.setattr(short_handles, "_move_room", crash)
    me = await whoami(client, signed_in_hub, AVERY)
    assert me["handle"] == "avery.quinn", "their request still goes through"
    await whoami(client, signed_in_hub, AVERY)
    assert (tries, ledger()) == (1, []), "not tried again on the very next request"

    monkeypatch.setattr(short_handles, "_move_room", real)
    short_handles._failed_until.clear()  # the wait has passed
    await whoami(client, signed_in_hub, AVERY)
    assert yaml.safe_load(stored("agents/builder")[1])["owner"] == "avery.quinn"
    assert len(ledger()) == 1


async def test_a_task_written_during_the_move_keeps_both_changes(
    client, signed_in_hub, monkeypatch: pytest.MonkeyPatch
):
    await _old_room(signed_in_hub, client)
    real = fields.upsert_patch
    raced = False

    async def someone_writes_first(room: str, key: str, *a: Any, **kw: Any) -> dict:
        nonlocal raced
        if key == "work/ship-it" and not raced:
            raced = True
            meta, content = stored(key)
            await real(room, key, meta, content, {"status": "done"}, OPERATOR)
        return await real(room, key, *a, **kw)

    monkeypatch.setattr(fields, "upsert_patch", someone_writes_first)
    await whoami(client, signed_in_hub, AVERY)
    meta = stored("work/ship-it")[0]
    assert raced
    assert meta["status"] == "done"
    assert meta["assignee"] == "@avery.quinn"


async def test_the_old_handle_still_means_its_person_and_nobody_else(client, signed_in_hub):
    await make_room(client, signed_in_hub)
    await whoami(client, signed_in_hub, AVERY)
    item = {"key": "context/plan", "value": "v1", "created_by": AVERY, "embed": False}
    mine = await client.post(
        f"/api/rooms/{ROOM}/memory", json={"items": [item]}, headers=signed_in_hub.headers(AVERY)
    )
    assert mine.status_code == 201, mine.text
    assert mine.json()[0]["created_by"] == "avery.quinn"

    theirs = await client.post(
        f"/api/rooms/{ROOM}/memory", json={"items": [item]}, headers=signed_in_hub.headers(OPERATOR)
    )
    assert theirs.status_code == 403
