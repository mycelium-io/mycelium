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
        json={"handle": "julia", "display_name": "Julia Valenti", "teams": ["Core"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["handle"] == "julia"
    assert body["teams"] == ["core"]  # normalized

    got = await client.get("/api/users/@Julia")
    assert got.status_code == 200
    assert got.json()["display_name"] == "Julia Valenti"


@pytest.mark.asyncio
async def test_unknown_user_404(client: AsyncClient):
    assert (await client.get("/api/users/nobody")).status_code == 404


@pytest.mark.asyncio
async def test_user_rollup_sums_owned_agent_budgets(client: AsyncClient):
    await client.post("/api/users", json={"handle": "julia", "teams": ["core"]})
    await _register_agent(
        client,
        "alpha",
        "a1",
        {"adapter": "claude_code", "cwd": "/tmp", "owner": "julia", "budget_usd_per_month": 5.0},
    )
    await _register_agent(
        client,
        "beta",
        "a2",
        {
            "adapter": "claude_code",
            "cwd": "/tmp",
            "owner": "julia",
            "team": "core",
            "budget_usd_per_month": 7.5,
        },
    )
    await _register_agent(
        client,
        "beta",
        "a3",
        {"adapter": "claude_code", "cwd": "/tmp", "owner": "sam", "budget_usd_per_month": 99.0},
    )

    user = (await client.get("/api/users/julia")).json()
    assert {o["handle"] for o in user["owns"]} == {"a1", "a2"}
    assert user["budget_usd_per_month"] == 12.5


@pytest.mark.asyncio
async def test_teams_rollup(client: AsyncClient):
    await client.post("/api/users", json={"handle": "julia", "teams": ["core"]})
    await _register_agent(
        client,
        "beta",
        "a2",
        {
            "adapter": "claude_code",
            "cwd": "/tmp",
            "owner": "julia",
            "team": "core",
            "budget_usd_per_month": 7.5,
        },
    )

    teams = {t["team"]: t for t in (await client.get("/api/teams")).json()["teams"]}
    assert "core" in teams
    assert teams["core"]["agent_count"] == 1
    assert teams["core"]["budget_usd_per_month"] == 7.5
    assert "julia" in teams["core"]["members"]
