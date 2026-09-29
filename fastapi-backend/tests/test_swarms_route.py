# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /rooms/{room}/swarms: a team of workers on a task in a room, from one write.

Through the app, node-free: the members, the task and the kickoff it makes in
the room it names; that it never makes a room; and that a room that has
swarmed before keeps its members.
"""

from __future__ import annotations

import subprocess

import pytest
import yaml

from app.services import persister, swarm, workspace
from app.services.filesystem import get_room_dir, list_memory_files, read_memory_file

ROOM = "general-engineering"


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


@pytest.fixture
async def room(client) -> str:
    resp = await client.post("/api/rooms", json={"name": ROOM, "is_public": True})
    assert resp.status_code in (200, 201), resp.text
    return ROOM


def _kind(room: str, handle: str) -> str | None:
    found = read_memory_file(get_room_dir(room), f"agents/{handle}")
    if found is None:
        return None
    return (yaml.safe_load(found[1]) or {}).get("kind")


@pytest.mark.asyncio
async def test_a_swarm_is_a_team_a_task_and_a_kickoff_in_the_room(client, room):
    resp = await client.post(
        f"/api/rooms/{room}/swarms",
        json={"task": "Write release notes for the 2.0 launch", "size": 3, "created_by": "julia"},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["room"] == room
    assert body["members"] == ["agent-1", "agent-2", "agent-3"]
    assert _kind(room, "conductor") == "conductor"
    assert [_kind(room, h) for h in body["members"]] == ["worker"] * 3
    rows = [key for key, _m, _c in list_memory_files(get_room_dir(room), prefix="work/")]
    assert rows == [body["key"]]
    assert body["episode"]

    said = [m for m in persister.prose_messages(room) if m.episode == body["episode"]]
    kickoff = [m.content for m in said] or [
        m["content"] for m in (await client.get(f"/api/rooms/{room}/messages")).json()["messages"]
    ]
    assert swarm.kickoff_text(body["members"], "Write release notes for the 2.0 launch") in kickoff


@pytest.mark.asyncio
async def test_a_swarm_never_makes_a_room(client):
    resp = await client.post("/api/rooms/nowhere/swarms", json={"task": "Anything"})

    assert resp.status_code == 404
    assert (await client.get("/api/rooms/nowhere")).status_code == 404


@pytest.mark.asyncio
async def test_a_room_that_swarmed_before_keeps_its_members(client, room):
    first = await client.post(f"/api/rooms/{room}/swarms", json={"task": "First task"})
    second = await client.post(f"/api/rooms/{room}/swarms", json={"task": "Second task", "size": 4})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["members"] == ["agent-1", "agent-2", "agent-3", "agent-4"]
    assert _kind(room, "agent-4") == "worker"
    assert first.json()["key"] != second.json()["key"]


@pytest.mark.asyncio
async def test_a_swarm_needs_a_task_and_a_sensible_size(client, room):
    url = f"/api/rooms/{room}/swarms"
    assert (await client.post(url, json={"task": "   "})).status_code == 422
    assert (await client.post(url, json={"task": "x", "size": 1})).status_code == 422
    assert (await client.post(url, json={"task": "x", "size": 99})).status_code == 422


@pytest.mark.asyncio
async def test_a_swarm_on_a_repository_clones_it_first(client, room, tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=upstream, check=True
        )

    resp = await client.post(
        f"/api/rooms/{room}/swarms", json={"task": "Add a health check", "repo": str(upstream)}
    )

    assert resp.status_code == 201, resp.text
    assert workspace.origin_of(room) == str(upstream)


@pytest.mark.asyncio
async def test_a_repository_the_hub_cannot_clone_starts_nothing(client, room, tmp_path):
    resp = await client.post(
        f"/api/rooms/{room}/swarms",
        json={"task": "Add a health check", "repo": str(tmp_path / "no")},
    )

    assert resp.status_code == 422
    assert "git clone failed" in resp.json()["detail"]
    assert _kind(room, "agent-1") is None
    assert list_memory_files(get_room_dir(room), prefix="work/") == []


@pytest.mark.asyncio
async def test_a_caller_can_post_the_kickoff_itself(client, room):
    resp = await client.post(
        f"/api/rooms/{room}/swarms", json={"task": "Plan the offsite", "kickoff": False}
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["key"]
    said = [m for m in persister.prose_messages(room) if m.episode == resp.json()["episode"]]
    assert said == []
