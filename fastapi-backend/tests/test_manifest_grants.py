# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Who may act as an agent is its owner's to say, not any writer's.

A manifest's ``owner`` and ``allow_from`` decide who may act as its agent, so
on a hub with sign-in on, the memory routes refuse a write or a delete that
changes them unless the caller may. Every other edit to a manifest still works.
"""

from __future__ import annotations

import pytest
import yaml
from httpx import AsyncClient

from app.services import principals
from app.services.filesystem import get_room_dir, read_memory_file, write_memory_file

ROOM = "grants-room"
OTHER = "other-room"


def _manifest(**fields: object) -> str:
    return yaml.safe_dump({"adapter": "claude_code", **fields})


def _seed(handle: str, room: str = ROOM, **fields: object) -> None:
    write_memory_file(
        get_room_dir(room), f"agents/{handle}", _manifest(**fields), created_by="seed"
    )


def _on_disk(handle: str, room: str = ROOM) -> dict:
    found = read_memory_file(get_room_dir(room), f"agents/{handle}")
    assert found is not None
    return yaml.safe_load(found[1])


async def _write(client: AsyncClient, key: str, value: str, by: str, room: str = ROOM):
    return await client.post(
        f"/api/rooms/{room}/memory",
        json={"items": [{"key": key, "value": value, "created_by": by, "embed": False}]},
    )


@pytest.fixture(autouse=True)
async def _rooms(client: AsyncClient) -> None:
    for name in (ROOM, OTHER):
        await client.post("/api/rooms", json={"name": name})
    _seed("lead", owner="julia", allow_from=["julia"], description="coordinates")


@pytest.mark.asyncio
async def test_the_owner_can_change_who_may_act_as_their_agent(client, as_principal):
    as_principal("julia", role="user")
    resp = await _write(
        client, "agents/lead", _manifest(owner="julia", allow_from=["sam"]), "julia"
    )
    assert resp.status_code == 201, resp.text
    assert _on_disk("lead")["allow_from"] == ["sam"]


@pytest.mark.asyncio
async def test_anyone_else_is_refused_and_nothing_changes(client, as_principal):
    as_principal("mallory", role="user")
    for change in (
        _manifest(owner="mallory", allow_from=["julia"]),
        _manifest(owner="julia", allow_from=["julia", "mallory"]),
        _manifest(description="mine now"),  # dropping both is a change too
    ):
        resp = await _write(client, "agents/lead", change, "mallory")
        assert resp.status_code == 403, resp.text
        assert "julia" in resp.json()["detail"]
    assert _on_disk("lead")["owner"] == "julia"
    assert _on_disk("lead")["allow_from"] == ["julia"]


@pytest.mark.asyncio
async def test_other_edits_to_a_manifest_still_work_for_its_writers(client, as_principal):
    # The agent itself edits its own description, keeping who may act as it.
    as_principal("lead")
    same_grants = _manifest(owner="julia", allow_from=["julia"], description="runs the release")
    resp = await _write(client, "agents/lead", same_grants, "lead")
    assert resp.status_code == 201, resp.text
    assert _on_disk("lead")["description"] == "runs the release"
    # But it can't hand itself to someone else.
    resp = await _write(client, "agents/lead", _manifest(owner="lead"), "lead")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_an_agent_s_notes_are_not_its_manifest(client, as_principal):
    as_principal("mallory", role="user")
    resp = await _write(client, "agents/lead/notes", "owner: mallory", "mallory")
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_only_the_owner_can_remove_the_manifest(client, as_principal):
    as_principal("mallory", role="user")
    assert (await client.delete(f"/api/rooms/{ROOM}/memory/agents/lead")).status_code == 403
    assert read_memory_file(get_room_dir(ROOM), "agents/lead") is not None
    as_principal("julia", role="user")
    assert (await client.delete(f"/api/rooms/{ROOM}/memory/agents/lead")).status_code == 204


@pytest.mark.asyncio
async def test_a_new_agent_is_yours_or_no_one_s(client, as_principal):
    as_principal("mallory", role="user")
    # Yours, with whoever you like allowed.
    mine = _manifest(owner="mallory", allow_from=["mallory", "sam"])
    assert (await _write(client, "agents/helper", mine, "mallory")).status_code == 201
    # No owner and no grants: an ordinary unowned agent, as before.
    assert (await _write(client, "agents/plain", _manifest(), "mallory")).status_code == 201
    # Not someone else's, and no grants without being its owner.
    theirs = await _write(client, "agents/helper2", _manifest(owner="julia"), "mallory")
    assert theirs.status_code == 403
    grants = await _write(client, "agents/helper3", _manifest(allow_from=["mallory"]), "mallory")
    assert grants.status_code == 403


@pytest.mark.asyncio
async def test_a_new_agent_can_t_take_someone_else_s_handle_in_another_room(client, as_principal):
    principals.write_user({"handle": "julia"})
    as_principal("mallory", role="user")
    # Julia's agent, made again in a room she isn't watching.
    lead = await _write(client, "agents/lead", _manifest(owner="mallory"), "mallory", room=OTHER)
    assert lead.status_code == 403
    assert OTHER not in lead.json()["detail"] and ROOM not in lead.json()["detail"]
    # A person's own handle.
    person = await _write(client, "agents/julia", _manifest(owner="mallory"), "mallory", room=OTHER)
    assert person.status_code == 403
    # Julia can add her own agent to another room.
    as_principal("julia", role="user")
    again = await _write(client, "agents/lead", _manifest(owner="julia"), "julia", room=OTHER)
    assert again.status_code == 201, again.text


@pytest.mark.asyncio
async def test_an_unowned_agent_is_claimed_only_by_itself_or_whom_it_allows(client, as_principal):
    _seed("old-bot", allow_from=["sam"])
    as_principal("mallory", role="user")
    claim = _manifest(owner="mallory", allow_from=["sam"])
    assert (await _write(client, "agents/old-bot", claim, "mallory")).status_code == 403
    as_principal("sam", role="user")
    claim = _manifest(owner="sam", allow_from=["sam"])
    assert (await _write(client, "agents/old-bot", claim, "sam")).status_code == 201


@pytest.mark.asyncio
async def test_with_sign_in_off_nothing_changes(client):
    resp = await _write(client, "agents/lead", _manifest(owner="mallory"), "mallory")
    assert resp.status_code == 201, resp.text
    assert _on_disk("lead")["owner"] == "mallory"
