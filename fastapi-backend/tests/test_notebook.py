"""Tests for notebook (agent-private) memory."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_notebook_write_and_read(client: AsyncClient):
    """Write a notebook memory and read it back."""
    # Write
    resp = await client.post(
        "/notebook/julia-agent/memory",
        json={
            "items": [
                {
                    "key": "identity/role",
                    "value": {"text": "Senior developer on mycelium"},
                    "created_by": "julia-agent",
                    "embed": False,
                }
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 1
    assert data[0]["key"] == "identity/role"
    assert data[0]["scope"] == "notebook"
    assert data[0]["owner_handle"] == "julia-agent"

    # Read it back
    resp = await client.get("/notebook/julia-agent/memory/identity/role")
    assert resp.status_code == 200
    assert resp.json()["value"]["text"] == "Senior developer on mycelium"


@pytest.mark.asyncio
async def test_notebook_privacy(client: AsyncClient):
    """Agent B cannot read agent A's notebook memories."""
    # Agent A writes
    await client.post(
        "/notebook/agent-a/memory",
        json={
            "items": [
                {
                    "key": "secret/preference",
                    "value": "I prefer tabs",
                    "created_by": "agent-a",
                    "embed": False,
                }
            ]
        },
    )

    # Agent B cannot read it
    resp = await client.get("/notebook/agent-b/memory/secret/preference")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_notebook_upsert(client: AsyncClient):
    """Notebook memories upsert correctly."""
    # Write v1
    resp = await client.post(
        "/notebook/agent-x/memory",
        json={
            "items": [
                {
                    "key": "status/mood",
                    "value": "focused",
                    "created_by": "agent-x",
                    "embed": False,
                }
            ]
        },
    )
    assert resp.json()[0]["version"] == 1

    # Upsert to v2
    resp = await client.post(
        "/notebook/agent-x/memory",
        json={
            "items": [
                {
                    "key": "status/mood",
                    "value": "tired",
                    "created_by": "agent-x",
                    "embed": False,
                }
            ]
        },
    )
    assert resp.json()[0]["version"] == 2


@pytest.mark.asyncio
async def test_notebook_list(client: AsyncClient):
    """List notebook memories filtered by handle."""
    # Write memories for two agents
    for agent in ["list-a", "list-b"]:
        await client.post(
            f"/notebook/{agent}/memory",
            json={
                "items": [
                    {
                        "key": f"context/{agent}-pref",
                        "value": f"pref for {agent}",
                        "created_by": agent,
                        "embed": False,
                    }
                ]
            },
        )

    # List agent A's notebook — should only see their own
    resp = await client.get("/notebook/list-a/memory")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["owner_handle"] == "list-a"


@pytest.mark.asyncio
async def test_notebook_delete(client: AsyncClient):
    """Delete a notebook memory."""
    await client.post(
        "/notebook/del-agent/memory",
        json={
            "items": [
                {
                    "key": "temp/note",
                    "value": "delete me",
                    "created_by": "del-agent",
                    "embed": False,
                }
            ]
        },
    )

    resp = await client.delete("/notebook/del-agent/memory/temp/note")
    assert resp.status_code == 204

    resp = await client.get("/notebook/del-agent/memory/temp/note")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_notebook_does_not_appear_in_room_memory(client: AsyncClient):
    """Notebook memories should not appear in namespace memory listings."""
    # Create a room
    await client.post("/rooms", json={"name": "nb-test-room"})

    # Write a notebook memory
    await client.post(
        "/notebook/nb-agent/memory",
        json={
            "items": [
                {
                    "key": "private/thought",
                    "value": "this is private",
                    "created_by": "nb-agent",
                    "embed": False,
                }
            ]
        },
    )

    # Write a namespace memory to the room
    await client.post(
        "/rooms/nb-test-room/memory",
        json={
            "items": [
                {
                    "key": "public/fact",
                    "value": "this is shared",
                    "created_by": "nb-agent",
                    "embed": False,
                }
            ]
        },
    )

    # List room memories — should only see namespace-scoped
    resp = await client.get("/rooms/nb-test-room/memory")
    assert resp.status_code == 200
    keys = [m["key"] for m in resp.json()]
    assert "public/fact" in keys
    assert "private/thought" not in keys
