# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for workspace / MAS / agent CRUD endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── Workspaces ────────────────────────────────────────────────────────────────


async def test_create_workspace(client: AsyncClient):
    resp = await client.post("/api/workspaces", json={"name": "my-workspace"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "my-workspace"
    assert "id" in body
    assert "created_at" in body


async def test_list_workspaces_empty(client: AsyncClient):
    resp = await client.get("/api/workspaces")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_workspaces(client: AsyncClient):
    await client.post("/api/workspaces", json={"name": "ws-a"})
    await client.post("/api/workspaces", json={"name": "ws-b"})
    resp = await client.get("/api/workspaces")
    assert resp.status_code == 200
    names = [w["name"] for w in resp.json()]
    assert "ws-a" in names
    assert "ws-b" in names


async def test_get_workspace(client: AsyncClient):
    created = (await client.post("/api/workspaces", json={"name": "ws1"})).json()
    resp = await client.get(f"/api/workspaces/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "ws1"


async def test_get_workspace_not_found(client: AsyncClient):
    resp = await client.get("/api/workspaces/00000000-0000-0000-0000-000000000099")
    assert resp.status_code == 404


async def test_delete_workspace(client: AsyncClient):
    created = (await client.post("/api/workspaces", json={"name": "ws-del"})).json()
    resp = await client.delete(f"/api/workspaces/{created['id']}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/workspaces/{created['id']}")).status_code == 404


# ── MAS ───────────────────────────────────────────────────────────────────────


async def test_create_mas(client: AsyncClient):
    ws = (await client.post("/api/workspaces", json={"name": "ws1"})).json()
    resp = await client.post(f"/api/workspaces/{ws['id']}/mas", json={"name": "my-mas"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "my-mas"
    assert body["workspace_id"] == ws["id"]


async def test_list_mas(client: AsyncClient):
    ws = (await client.post("/api/workspaces", json={"name": "ws1"})).json()
    await client.post(f"/api/workspaces/{ws['id']}/mas", json={"name": "mas-a"})
    await client.post(f"/api/workspaces/{ws['id']}/mas", json={"name": "mas-b"})
    resp = await client.get(f"/api/workspaces/{ws['id']}/mas")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_mas_workspace_not_found(client: AsyncClient):
    resp = await client.post(
        "/api/workspaces/00000000-0000-0000-0000-000000000099/mas",
        json={"name": "mas1"},
    )
    assert resp.status_code == 404


async def test_delete_mas(client: AsyncClient):
    ws = (await client.post("/api/workspaces", json={"name": "ws1"})).json()
    mas = (await client.post(f"/api/workspaces/{ws['id']}/mas", json={"name": "mas1"})).json()
    resp = await client.delete(f"/api/workspaces/{ws['id']}/mas/{mas['id']}")
    assert resp.status_code == 204


# ── Agents ────────────────────────────────────────────────────────────────────


async def test_create_agent(client: AsyncClient):
    ws = (await client.post("/api/workspaces", json={"name": "ws1"})).json()
    mas = (await client.post(f"/api/workspaces/{ws['id']}/mas", json={"name": "mas1"})).json()
    resp = await client.post(
        f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents",
        json={"name": "agent-alpha", "memory_provider_url": "http://mem:8080"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "agent-alpha"
    assert body["memory_provider_url"] == "http://mem:8080"
    assert body["mas_id"] == mas["id"]


async def test_list_agents(client: AsyncClient):
    ws = (await client.post("/api/workspaces", json={"name": "ws1"})).json()
    mas = (await client.post(f"/api/workspaces/{ws['id']}/mas", json={"name": "mas1"})).json()
    await client.post(f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents", json={"name": "a1"})
    await client.post(f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents", json={"name": "a2"})
    resp = await client.get(f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_patch_agent(client: AsyncClient):
    ws = (await client.post("/api/workspaces", json={"name": "ws1"})).json()
    mas = (await client.post(f"/api/workspaces/{ws['id']}/mas", json={"name": "mas1"})).json()
    agent = (
        await client.post(
            f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents",
            json={"name": "old-name"},
        )
    ).json()
    resp = await client.patch(
        f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents/{agent['id']}",
        json={"name": "new-name", "memory_provider_url": "http://updated:9000"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "new-name"
    assert body["memory_provider_url"] == "http://updated:9000"


async def test_delete_agent(client: AsyncClient):
    ws = (await client.post("/api/workspaces", json={"name": "ws1"})).json()
    mas = (await client.post(f"/api/workspaces/{ws['id']}/mas", json={"name": "mas1"})).json()
    agent = (
        await client.post(
            f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents",
            json={"name": "agent1"},
        )
    ).json()
    resp = await client.delete(f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents/{agent['id']}")
    assert resp.status_code == 204
    assert (
        await client.get(f"/api/workspaces/{ws['id']}/mas/{mas['id']}/agents/{agent['id']}")
    ).status_code == 404
