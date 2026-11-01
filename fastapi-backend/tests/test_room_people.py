# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room's people are recorded when they join, never guessed from who posted."""

from __future__ import annotations

import pytest
import yaml

from app.services import message_format, persister, principals, room_people
from app.services.filesystem import delete_memory_file, get_room_dir, write_memory_file
from app.services.message_models import Kind


def _user(handle: str) -> None:
    principals.write_user({"handle": handle})


def _agent(
    room: str, handle: str, *, owner: str | None = None, adapter: str = "claude_code"
) -> None:
    body = yaml.safe_dump({"adapter": adapter, "owner": owner} if owner else {"adapter": adapter})
    write_memory_file(get_room_dir(room), f"agents/{handle}", body, created_by="test")


async def _post(client, room: str, sender: str, text: str = "hello") -> None:
    resp = await client.post(
        f"/api/rooms/{room}/messages",
        json={"sender_handle": sender, "content": text, "message_type": "broadcast"},
    )
    assert resp.status_code == 201, resp.text


async def _members(client, room: str) -> dict:
    resp = await client.get(f"/api/rooms/{room}/members")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _people(members: dict) -> dict[str, str]:
    return {p["handle"]: p["via"] for p in members["people"]}


@pytest.mark.asyncio
async def test_whoever_makes_a_room_is_its_first_person(client):
    _user("julia")
    await client.post("/api/rooms", json={"name": "plans", "owner": "julia"})
    assert _people(await _members(client, "plans")) == {"julia": "created"}

    # An owner with no user record made the room, but isn't a person in it.
    await client.post("/api/rooms", json={"name": "scripted", "owner": "ci-bot"})
    assert _people(await _members(client, "scripted")) == {}


@pytest.mark.asyncio
async def test_a_person_who_posts_joins_and_nobody_else_does(client):
    _user("julia")
    _user("sam")
    await client.post("/api/rooms", json={"name": "plans", "owner": "julia"})
    _agent("plans", "coder", owner="julia")

    await _post(client, "plans", "sam")
    await _post(client, "plans", "coder")
    await _post(client, "plans", "ghost")

    members = await _members(client, "plans")
    assert _people(members) == {"julia": "created", "sam": "message"}
    assert [a["handle"] for a in members["agents"]] == ["coder"]


@pytest.mark.asyncio
async def test_a_restarted_agent_never_appears_under_people(client):
    """Its manifest gone for a moment, it posts and is present, and still isn't a person."""
    _user("julia")
    await client.post("/api/rooms", json={"name": "plans", "owner": "julia"})
    _agent("plans", "coder", owner="julia")
    await _post(client, "plans", "coder")

    delete_memory_file(get_room_dir("plans"), "agents/coder")
    await _post(client, "plans", "coder", "back after a restart")
    assert "coder" not in _people(await _members(client, "plans"))

    _agent("plans", "coder", owner="julia")
    members = await _members(client, "plans")
    assert _people(members) == {"julia": "created"}
    assert [a["handle"] for a in members["agents"]] == ["coder"]


@pytest.mark.asyncio
async def test_a_handle_with_no_user_record_is_never_a_person(client):
    await client.post("/api/rooms", json={"name": "plans"})
    resp = await client.post("/api/rooms/plans/members", json={"handle": "ghost"})
    assert resp.status_code == 422

    _agent("plans", "coder")
    _user("coder")  # a user record doesn't make an agent here a person
    resp = await client.post("/api/rooms/plans/members", json={"handle": "coder"})
    assert resp.status_code == 422
    assert _people(await _members(client, "plans")) == {}


@pytest.mark.asyncio
async def test_adding_and_removing_a_person(client):
    _user("julia")
    _user("sam")
    await client.post("/api/rooms", json={"name": "plans", "owner": "julia"})

    added = await client.post("/api/rooms/plans/members", json={"handle": "@Sam"})
    assert added.status_code == 201
    assert added.json()["handle"] == "sam"
    assert added.json()["via"] == "added"
    again = await client.post("/api/rooms/plans/members", json={"handle": "sam"})
    assert again.json()["joined_at"] == added.json()["joined_at"]

    assert (await client.delete("/api/rooms/plans/members/sam")).status_code == 204
    assert _people(await _members(client, "plans")) == {"julia": "created"}
    assert (await client.delete("/api/rooms/plans/members/sam")).status_code == 404

    # Out until they join again: posting is joining.
    await _post(client, "plans", "sam")
    assert _people(await _members(client, "plans")) == {"julia": "created", "sam": "message"}


@pytest.mark.asyncio
async def test_on_a_gated_hub_you_remove_yourself_and_the_owner_removes_anyone(
    client, as_principal
):
    for handle in ("julia", "sam", "avery"):
        _user(handle)
    await client.post("/api/rooms", json={"name": "plans", "owner": "julia"})
    for handle in ("sam", "avery"):
        await client.post("/api/rooms/plans/members", json={"handle": handle})

    as_principal("sam", role="user")
    assert (await client.delete("/api/rooms/plans/members/avery")).status_code == 403
    assert (await client.delete("/api/rooms/plans/members/sam")).status_code == 204
    as_principal("julia", role="user")
    assert (await client.delete("/api/rooms/plans/members/avery")).status_code == 204


@pytest.mark.asyncio
async def test_an_existing_room_is_seeded_once_with_only_its_people(client):
    """A room from before rooms kept a list: its posters, owners and members, users only."""
    _user("julia")
    _user("sam")
    _user("avery")
    room = "older"
    get_room_dir(room)
    _agent(room, "coder", owner="avery")
    for sender in ("sam", "coder", "ghost"):
        env = message_format.build_envelope(
            kind=Kind.exchange,
            episode=message_format.episode_urn(room, "live"),
            sender=sender,
            sender_role="human",
            recipients=[],
            topic=message_format.topic_urn(room),
            payload_type="message",
        )
        persister.append_transcript(room, persister.record_from(env, {"content": "hi"}))

    assert _people(await _members(client, room)) == {"sam": "seeded", "avery": "seeded"}

    # Seeded once: taking someone out sticks, and julia isn't added by a read.
    assert (await client.delete(f"/api/rooms/{room}/members/sam")).status_code == 204
    assert _people(await _members(client, room)) == {"avery": "seeded"}


@pytest.mark.asyncio
async def test_a_handle_holding_a_task_is_listed_under_others(client):
    await client.post("/api/rooms", json={"name": "plans"})
    write_memory_file(
        get_room_dir("plans"),
        "work/fix-login",
        "Fix login",
        created_by="test",
        extra_meta={"assignee": "ghost"},
    )
    members = await _members(client, "plans")
    assert members["people"] == []
    assert members["others"] == [{"handle": "ghost", "holds_task": True, "present": False}]


@pytest.mark.asyncio
async def test_a_private_room_is_listed_for_its_people(client):
    _user("julia")
    _user("sam")
    await client.post("/api/rooms", json={"name": "diary", "is_public": False, "owner": "julia"})

    async def listed_for(viewer: str) -> bool:
        rooms = (await client.get("/api/rooms", params={"viewer": viewer})).json()
        return "diary" in {r["name"] for r in rooms}

    assert not await listed_for("sam")
    await client.post("/api/rooms/diary/members", json={"handle": "sam"})
    assert await listed_for("sam")
    assert (await client.get("/api/rooms/diary")).json()["members"] == ["sam"]

    # Taken out: no longer one of its people, and no longer listed for them.
    await client.delete("/api/rooms/diary/members/sam")
    assert not await listed_for("sam")
    assert (await client.get("/api/rooms/diary")).json()["members"] == []


@pytest.mark.asyncio
async def test_posting_in_a_private_room_doesnt_join_it_or_list_it(client):
    """Anyone who knows a private room's name can post in it; that isn't joining."""
    _user("julia")
    _user("stranger")
    await client.post("/api/rooms", json={"name": "diary", "is_public": False, "owner": "julia"})

    await _post(client, "diary", "stranger", "found you")

    assert _people(await _members(client, "diary")) == {"julia": "created"}
    rooms = (await client.get("/api/rooms", params={"viewer": "stranger"})).json()
    assert "diary" not in {r["name"] for r in rooms}


@pytest.mark.asyncio
async def test_a_private_room_is_seeded_with_only_its_owner_and_members(client):
    for handle in ("julia", "sam", "stranger", "avery"):
        _user(handle)
    await client.post(
        "/api/rooms",
        json={"name": "diary", "is_public": False, "owner": "julia", "members": ["sam"]},
    )
    (get_room_dir("diary") / room_people.FILENAME).unlink()  # a room from before the list
    _agent("diary", "coder", owner="avery")
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.episode_urn("diary", "live"),
        sender="stranger",
        sender_role="human",
        recipients=[],
        topic=message_format.topic_urn("diary"),
        payload_type="message",
    )
    persister.append_transcript("diary", persister.record_from(env, {"content": "hi"}))

    assert _people(await _members(client, "diary")) == {"julia": "seeded", "sam": "seeded"}


def test_a_new_room_lists_its_owner_and_members_who_are_people():
    _user("julia")
    get_room_dir("fresh")
    room_people.start("fresh", "julia", ["sam", "julia"])
    assert [(p["handle"], p["via"]) for p in room_people.people("fresh")] == [("julia", "created")]
