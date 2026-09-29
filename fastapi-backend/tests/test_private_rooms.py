# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Private rooms: listed, streamed and searched only for their owner and members."""

from __future__ import annotations

import pytest

from app.services import room_access


async def _names(client, viewer: str | None = None) -> set[str]:
    params = {"viewer": viewer} if viewer else {}
    resp = await client.get("/api/rooms", params=params)
    assert resp.status_code == 200
    return {r["name"] for r in resp.json()}


@pytest.mark.asyncio
async def test_a_private_room_is_listed_for_its_owner_and_members_only(client):
    await client.post("/api/rooms", json={"name": "open-room"})
    made = await client.post(
        "/api/rooms",
        json={"name": "diary", "is_public": False, "owner": "@Julia", "members": ["sam", "julia"]},
    )
    assert made.status_code == 201
    assert made.json()["owner"] == "julia"
    assert made.json()["members"] == ["sam"]

    assert await _names(client, "julia") == {"open-room", "diary"}
    assert await _names(client, "sam") == {"open-room", "diary"}
    assert await _names(client, "avery") == {"open-room"}
    assert await _names(client) == {"open-room"}


@pytest.mark.asyncio
async def test_a_private_room_needs_an_owner(client):
    resp = await client.post("/api/rooms", json={"name": "nobodys", "is_public": False})
    assert resp.status_code == 422
    assert "owner" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_room_can_be_made_private_and_shared_again(client):
    await client.post("/api/rooms", json={"name": "planning"})

    private = await client.patch("/api/rooms/planning", json={"is_public": False, "by": "julia"})
    assert private.status_code == 200
    assert private.json()["is_public"] is False
    assert private.json()["owner"] == "julia"
    assert "planning" not in await _names(client, "avery")
    assert "planning" in await _names(client, "julia")

    shared = await client.patch("/api/rooms/planning", json={"members": ["avery"]})
    assert shared.json()["members"] == ["avery"]
    assert "planning" in await _names(client, "avery")

    public = await client.patch("/api/rooms/planning", json={"is_public": True})
    assert public.json()["is_public"] is True
    assert "planning" in await _names(client)


@pytest.mark.asyncio
async def test_making_a_room_private_needs_someone_to_own_it(client):
    await client.post("/api/rooms", json={"name": "orphan"})
    resp = await client.patch("/api/rooms/orphan", json={"is_public": False})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_leaves_out_someone_elses_private_room_unless_it_is_named(client):
    from app.services import search, search_query

    await client.post("/api/rooms", json={"name": "open-room"})
    await client.post(
        "/api/rooms", json={"name": "secret-plans", "is_public": False, "owner": "julia"}
    )

    everything = search_query.parse("plans")
    assert search._rooms_in_scope(everything, "avery") == ["open-room"]
    assert set(search._rooms_in_scope(everything, "julia")) == {"open-room", "secret-plans"}
    # Naming it is knowing it, the same as opening it by name anywhere else.
    assert search._rooms_in_scope(search_query.parse("#secret-plans x"), "avery") == [
        "secret-plans"
    ]


def test_visibility_rules():
    shared = {"is_public": True}
    private = {"is_public": False, "owner": "julia", "members": ["sam"]}
    assert room_access.visible_to(shared, None)
    assert room_access.visible_to(private, "julia")
    assert room_access.visible_to(private, "sam")
    assert not room_access.visible_to(private, "avery")
    assert not room_access.visible_to(private, None)
    # A room hidden before owners existed stays hidden from everyone.
    assert not room_access.visible_to({"is_public": False}, "julia")
    assert not room_access.visible_to(None, "julia")
