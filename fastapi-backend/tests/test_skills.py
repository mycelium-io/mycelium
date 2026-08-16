# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Skills API — the room-scoped ``skills/`` memory namespace, promoted (#617)."""

import pytest


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    """Skills are memories, so a create embeds like any memory write; stub the
    embedder so the fastembed ONNX model never loads (it PermissionErrors on the
    ``/opt/fastembed`` cache in sandbox envs). CI exports MYCELIUM_STUB_EMBEDDINGS."""
    monkeypatch.setattr("app.services.embedding._STUB", True)


async def _make_room(client, name: str = "demo") -> None:
    await client.post("/api/rooms", json={"name": name})


@pytest.mark.asyncio
async def test_create_get_and_list_skill(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/demo/skills",
        json={
            "name": "summarize-room",
            "description": "Condense the room's decisions.",
            "body": "Read decisions/ and produce a 5-bullet brief.",
            "tags": ["reporting"],
            "created_by": "julia",
        },
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "summarize-room"
    assert created["version"] == 1
    assert created["created_by"] == "julia"
    assert created["description"] == "Condense the room's decisions."

    got = await client.get("/api/rooms/demo/skills/summarize-room")
    assert got.status_code == 200
    body = got.json()
    assert body["body"] == "Read decisions/ and produce a 5-bullet brief."
    assert body["description"] == "Condense the room's decisions."

    listing = await client.get("/api/rooms/demo/skills")
    assert listing.status_code == 200
    data = listing.json()
    assert data["total"] == 1
    assert data["skills"][0]["name"] == "summarize-room"


@pytest.mark.asyncio
async def test_skill_is_reachable_as_a_memory(client):
    """A skill is a memory under skills/ — the promoted-view model (#617)."""
    await _make_room(client)
    await client.post(
        "/api/rooms/demo/skills",
        json={"name": "brief", "body": "the body", "created_by": "julia"},
    )
    mem = await client.get("/api/rooms/demo/memory/skills/brief")
    assert mem.status_code == 200
    assert mem.json()["key"] == "skills/brief"


@pytest.mark.asyncio
async def test_upsert_bumps_version_and_preserves_author(client):
    await _make_room(client)
    await client.post(
        "/api/rooms/demo/skills",
        json={"name": "brief", "body": "v1", "created_by": "julia"},
    )
    resp = await client.post(
        "/api/rooms/demo/skills",
        json={"name": "brief", "body": "v2", "created_by": "sam"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["version"] == 2
    assert body["created_by"] == "julia"  # original author preserved
    assert body["updated_by"] == "sam"
    assert body["body"] == "v2"


@pytest.mark.asyncio
async def test_get_missing_skill_is_404(client):
    await _make_room(client)
    resp = await client.get("/api/rooms/demo/skills/nope")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_room_is_404(client):
    resp = await client.get("/api/rooms/ghost/skills")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_skill(client):
    await _make_room(client)
    await client.post(
        "/api/rooms/demo/skills",
        json={"name": "temp", "body": "x", "created_by": "julia"},
    )
    resp = await client.delete("/api/rooms/demo/skills/temp")
    assert resp.status_code == 204
    assert (await client.get("/api/rooms/demo/skills/temp")).status_code == 404
    assert (await client.delete("/api/rooms/demo/skills/temp")).status_code == 404


@pytest.mark.asyncio
async def test_invalid_skill_name_rejected(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/demo/skills",
        json={"name": "Bad Name!", "body": "x", "created_by": "julia"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_skill_created_via_plain_memory_set_is_listed(client):
    """The uniform model: a skills/ memory written directly shows up as a skill."""
    await _make_room(client)
    await client.post(
        "/api/rooms/demo/memory",
        json={"items": [{"key": "skills/adhoc", "value": "just prose", "created_by": "julia"}]},
    )
    listing = await client.get("/api/rooms/demo/skills")
    names = [s["name"] for s in listing.json()["skills"]]
    assert "adhoc" in names
