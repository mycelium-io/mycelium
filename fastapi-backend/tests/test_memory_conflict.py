# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Conflict-policy tests (§11): last-write-wins by version; a write on a stale
base is rejected with details. No merge handler.
"""

import pytest
from httpx import AsyncClient


async def _write(client, room, key, value, created_by, **extra):
    return await client.post(
        f"/api/rooms/{room}/memory",
        json={
            "items": [
                {"key": key, "value": value, "created_by": created_by, "embed": False, **extra}
            ]
        },
    )


@pytest.mark.asyncio
async def test_last_write_wins_without_base(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "lww"})
    r1 = await _write(client, "lww", "k", "first", "a")
    assert r1.json()[0]["version"] == 1

    r2 = await _write(client, "lww", "k", "second", "b")
    assert r2.status_code == 201
    assert r2.json()[0]["version"] == 2
    assert r2.json()[0]["updated_by"] == "b"

    got = await client.get("/api/rooms/lww/memory/k")
    assert got.json()["value"] == {"text": "second"}


@pytest.mark.asyncio
async def test_matching_base_accepted(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "cas-ok"})
    await _write(client, "cas-ok", "k", "first", "a")

    r2 = await _write(client, "cas-ok", "k", "second", "b", base_version=1)
    assert r2.status_code == 201
    assert r2.json()[0]["version"] == 2


@pytest.mark.asyncio
async def test_base_zero_on_fresh_key_accepted(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "cas-new"})
    r = await _write(client, "cas-new", "fresh", "x", "a", base_version=0)
    assert r.status_code == 201
    assert r.json()[0]["version"] == 1


@pytest.mark.asyncio
async def test_stale_base_rejected_with_details(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "cas-stale"})
    await _write(client, "cas-stale", "k", "current-value", "alice")

    # Base 0 is stale — current version is 1.
    resp = await _write(client, "cas-stale", "k", "clobber", "bob", base_version=0)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "stale_base"
    assert detail["current_version"] == 1
    assert detail["current_content"] == "current-value"
    assert detail["updated_by"] == "alice"
    assert detail["updated_at"] is not None

    # The rejected write did not change anything.
    got = await client.get("/api/rooms/cas-stale/memory/k")
    assert got.json()["version"] == 1
    assert got.json()["value"] == {"text": "current-value"}
