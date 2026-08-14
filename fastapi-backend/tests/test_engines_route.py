# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /rooms/{room}/engines — native engine invite.

Engines are backend-owned (no machine-local side effects), so the web UI can
register one directly. These tests assert the manifest lands where the summon
seam and the agents listing read it, and that validation fails closed.
"""

import pytest

from app.services.aligner import _registered_engine_kind


async def _make_room(client, name: str = "portfolio") -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_invite_engine_registers_recognized_manifest(client):
    await _make_room(client)

    resp = await client.post(
        "/api/rooms/portfolio/engines",
        json={"handle": "aligner", "kind": "aligner", "description": "mediate us"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["handle"] == "aligner"
    assert body["adapter"] == "engine"
    assert body["kind"] == "aligner"

    # It appears in the structured agents listing…
    agents = (await client.get("/api/rooms/portfolio/agents")).json()
    assert any(a["handle"] == "aligner" and a["adapter"] == "engine" for a in agents)

    # …and the aligner summon seam recognizes it identically to a CLI-created one.
    assert _registered_engine_kind("portfolio", "aligner") == "aligner"


@pytest.mark.asyncio
async def test_invite_normalizes_handle_and_synthesizer_kind(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/engines",
        json={"handle": "@Distiller", "kind": "synthesizer"},
    )
    assert resp.status_code == 201
    assert resp.json()["handle"] == "distiller"
    assert _registered_engine_kind("portfolio", "distiller") == "synthesizer"


@pytest.mark.asyncio
async def test_duplicate_handle_conflicts(client):
    await _make_room(client)
    body = {"handle": "aligner", "kind": "aligner"}
    assert (await client.post("/api/rooms/portfolio/engines", json=body)).status_code == 201
    assert (await client.post("/api/rooms/portfolio/engines", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_unknown_kind_rejected(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/engines", json={"handle": "foo", "kind": "bogus"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_handle_rejected(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/engines", json={"handle": "Bad Handle!", "kind": "aligner"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_room_404(client):
    resp = await client.post(
        "/api/rooms/nope/engines", json={"handle": "aligner", "kind": "aligner"}
    )
    assert resp.status_code == 404
