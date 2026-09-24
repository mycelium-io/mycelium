# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /swarms: a team of workers on a task, from one write.

Through the app, node-free: the room, the members, the task and the kickoff
it makes, and that it reuses a room it is pointed at rather than failing on
the members already there.
"""

from __future__ import annotations

import pytest
import yaml

from app.services import persister, swarm
from app.services.filesystem import get_room_dir, list_memory_files, read_memory_file


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


def _kind(room: str, handle: str) -> str | None:
    found = read_memory_file(get_room_dir(room), f"agents/{handle}")
    if found is None:
        return None
    return (yaml.safe_load(found[1]) or {}).get("kind")


@pytest.mark.asyncio
async def test_a_swarm_is_a_room_a_team_a_task_and_a_kickoff(client):
    resp = await client.post(
        "/api/swarms",
        json={"task": "Write release notes for the 2.0 launch", "size": 3, "created_by": "julia"},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["room"] == "write-release-notes-2-0-launch"
    assert body["members"] == ["agent-1", "agent-2", "agent-3"]
    room = body["room"]
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
async def test_a_room_can_be_reused_and_its_members_are_kept(client):
    first = await client.post("/api/swarms", json={"task": "First task", "room": "team-room"})
    second = await client.post(
        "/api/swarms", json={"task": "Second task", "room": "team-room", "size": 4}
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["room"] == "team-room"
    assert second.json()["members"] == ["agent-1", "agent-2", "agent-3", "agent-4"]
    assert _kind("team-room", "agent-4") == "worker"
    assert first.json()["key"] != second.json()["key"]


@pytest.mark.asyncio
async def test_a_swarm_needs_a_task_and_a_sensible_size(client):
    assert (await client.post("/api/swarms", json={"task": "   "})).status_code == 422
    assert (await client.post("/api/swarms", json={"task": "x", "size": 1})).status_code == 422
    assert (await client.post("/api/swarms", json={"task": "x", "size": 99})).status_code == 422
