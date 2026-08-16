# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Skills store API — the global, folder-based skills namespace (#617)."""

import pytest


@pytest.mark.asyncio
async def test_create_get_and_list_skill(client):
    resp = await client.post(
        "/api/skills",
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

    got = await client.get("/api/skills/summarize-room")
    assert got.status_code == 200
    assert got.json()["body"] == "Read decisions/ and produce a 5-bullet brief."

    listing = await client.get("/api/skills")
    assert listing.status_code == 200
    data = listing.json()
    assert data["total"] == 1
    assert data["skills"][0]["name"] == "summarize-room"


@pytest.mark.asyncio
async def test_upsert_bumps_version_and_preserves_author(client):
    await client.post(
        "/api/skills",
        json={"name": "brief", "body": "v1", "created_by": "julia"},
    )
    resp = await client.post(
        "/api/skills",
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
    resp = await client.get("/api/skills/nope")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_skill(client):
    await client.post("/api/skills", json={"name": "temp", "body": "x", "created_by": "julia"})
    resp = await client.delete("/api/skills/temp")
    assert resp.status_code == 204
    assert (await client.get("/api/skills/temp")).status_code == 404
    assert (await client.delete("/api/skills/temp")).status_code == 404


@pytest.mark.asyncio
async def test_invalid_skill_name_rejected(client):
    resp = await client.post(
        "/api/skills",
        json={"name": "Bad Name!", "body": "x", "created_by": "julia"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unmanaged_frontmatter_survives_rewrite(client):
    await client.post(
        "/api/skills",
        json={"name": "keep", "body": "v1", "created_by": "julia", "meta": {"owner_team": "ops"}},
    )
    resp = await client.post(
        "/api/skills",
        json={"name": "keep", "body": "v2", "created_by": "julia"},
    )
    assert resp.status_code == 201
    # Round-trips through the file; unmanaged meta is preserved (not asserted in
    # the API shape, but must not break the write).
    got = await client.get("/api/skills/keep")
    assert got.json()["body"] == "v2"
