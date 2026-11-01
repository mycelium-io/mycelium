# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Two machines' agents in one room, over the hub's own routes.

Each machine's runner pushes only its own agents' presence and drains the
room's wakes every few seconds. Pushed in turn, neither removes the other's
agents, and each machine is handed only its own agents' wakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import room_channels

ROOM = "two-machines"


async def _push(client: AsyncClient, source: str, statuses: dict) -> None:
    response = await client.post(
        f"/api/rooms/{ROOM}/sessions/herdr-presence",
        json={"statuses": statuses, "ttl_s": 90, "source": source},
    )
    assert response.status_code == 204


async def _drain(client: AsyncClient, source: str) -> list[str]:
    response = await client.get(
        f"/api/rooms/{ROOM}/sessions/herdr-wakes", params={"source": source}
    )
    assert response.status_code == 200
    return [w["handle"] for w in response.json()["wakes"]]


@pytest.mark.asyncio
async def test_each_machine_wakes_the_other_machines_agent_every_pass(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    await client.post("/api/rooms", json={"name": ROOM})
    manager = room_channels.manager
    # No transcript to check what's unread against, so each wake goes as it is.
    monkeypatch.setattr(manager, "get", lambda _room: None)
    for _ in range(10):
        # Ana's runner, then Ben's, each with only its own agent.
        await _push(client, "laptop-ana", {"ana-agent": {"status": "idle"}})
        await _push(client, "laptop-ben", {"ben-agent": {"status": "idle"}})
        # Each person mentions the other's agent: both are present to ring.
        assert manager.ring_asked(ROOM, "ben-agent", "mention", sender="ana")
        assert manager.ring_asked(ROOM, "ana-agent", "mention", sender="ben")
        # Whichever runner drains first takes only its own agent's wake.
        assert await _drain(client, "laptop-ana") == ["ana-agent"]
        assert await _drain(client, "laptop-ben") == ["ben-agent"]
