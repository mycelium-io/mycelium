# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Principal layer — user store, owner/team roll-ups, endpoints.

No database: users are markdown records under a temp ``users/`` dir and agent
manifests are memory entries under each room. Trust is self-asserted.
"""

import pytest
from httpx import AsyncClient


async def _register_agent(client: AsyncClient, room: str, handle: str, manifest: dict) -> None:
    """Write an agent manifest the way the CLI does — a memory entry (YAML body)."""
    import yaml

    await client.post("/api/rooms", json={"name": room})
    await client.post(
        f"/api/rooms/{room}/memory",
        json={
            "items": [
                {
                    "key": f"agents/{handle}",
                    "value": yaml.safe_dump(manifest, sort_keys=False),
                    "created_by": "tester",
                    "embed": False,
                    "tags": ["agent-manifest"],
                }
            ]
        },
    )


@pytest.mark.asyncio
async def test_create_and_get_user(client: AsyncClient):
    resp = await client.post(
        "/api/users",
        json={"handle": "avery", "display_name": "Avery Quinn", "teams": ["Core"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["handle"] == "avery"
    assert body["teams"] == ["core"]  # normalized

    got = await client.get("/api/users/@Avery")
    assert got.status_code == 200
    assert got.json()["display_name"] == "Avery Quinn"


@pytest.mark.asyncio
async def test_unknown_user_404(client: AsyncClient):
    assert (await client.get("/api/users/nobody")).status_code == 404


@pytest.mark.asyncio
async def test_user_rollup_lists_owned_agents(client: AsyncClient):
    await client.post("/api/users", json={"handle": "avery", "teams": ["core"]})
    await _register_agent(
        client,
        "alpha",
        "a1",
        {"adapter": "claude_code", "cwd": "/tmp", "owner": "avery"},
    )
    await _register_agent(
        client,
        "beta",
        "a2",
        {"adapter": "claude_code", "cwd": "/tmp", "owner": "avery", "team": "core"},
    )
    await _register_agent(
        client,
        "beta",
        "a3",
        {"adapter": "claude_code", "cwd": "/tmp", "owner": "sam"},
    )

    user = (await client.get("/api/users/avery")).json()
    assert {o["handle"] for o in user["owns"]} == {"a1", "a2"}


@pytest.mark.asyncio
async def test_teams_rollup(client: AsyncClient):
    await client.post("/api/users", json={"handle": "avery", "teams": ["core"]})
    await _register_agent(
        client,
        "beta",
        "a2",
        {"adapter": "claude_code", "cwd": "/tmp", "owner": "avery", "team": "core"},
    )

    teams = {t["team"]: t for t in (await client.get("/api/teams")).json()["teams"]}
    assert "core" in teams
    assert teams["core"]["agent_count"] == 1
    assert "avery" in teams["core"]["members"]
