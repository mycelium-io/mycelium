# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /rooms/{room}/engines — native engine invite.

Engines are backend-owned (no machine-local side effects), so the web UI can
register one directly. These tests assert the manifest lands where the summon
seam and the agents listing read it, and that validation fails closed.
"""

import json
from pathlib import Path

import pytest

from app.routes.engines import ENGINE_KINDS
from app.services.engine_kinds import registered_engine_kind
from app.services.retired_aligner import RETIRED_KIND, RETIRED_TEXT

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "engine-kinds.json").read_text()
)


def test_the_kinds_and_the_retired_line_match_the_contract():
    assert sorted(ENGINE_KINDS) == CONTRACT["kinds"]
    assert CONTRACT["retired"] == {RETIRED_KIND: RETIRED_TEXT}


async def _make_room(client, name: str = "portfolio") -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_invite_engine_registers_recognized_manifest(client):
    await _make_room(client)

    resp = await client.post(
        "/api/rooms/portfolio/engines",
        json={"handle": "conductor", "kind": "conductor", "description": "walk us through it"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["handle"] == "conductor"
    assert body["adapter"] == "engine"
    assert body["kind"] == "conductor"

    # It appears in the structured agents listing…
    agents = (await client.get("/api/rooms/portfolio/agents")).json()
    assert any(a["handle"] == "conductor" and a["adapter"] == "engine" for a in agents)

    # …and the summon seam recognizes it identically to a CLI-created one.
    assert registered_engine_kind("portfolio", "conductor") == "conductor"


@pytest.mark.asyncio
async def test_invite_normalizes_handle_and_synthesizer_kind(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/engines",
        json={"handle": "@Distiller", "kind": "synthesizer"},
    )
    assert resp.status_code == 201
    assert resp.json()["handle"] == "distiller"
    assert registered_engine_kind("portfolio", "distiller") == "synthesizer"


@pytest.mark.asyncio
async def test_invite_hello_kind(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/engines",
        json={"handle": "hello", "kind": "hello"},
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "hello"
    assert registered_engine_kind("portfolio", "hello") == "hello"


@pytest.mark.asyncio
async def test_duplicate_handle_conflicts(client):
    await _make_room(client)
    body = {"handle": "conductor", "kind": "conductor"}
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
async def test_the_retired_aligner_kind_says_what_to_run_instead(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/engines", json={"handle": "aligner", "kind": "aligner"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == RETIRED_TEXT
    assert registered_engine_kind("portfolio", "aligner") is None


@pytest.mark.asyncio
async def test_invalid_handle_rejected(client):
    await _make_room(client)
    resp = await client.post(
        "/api/rooms/portfolio/engines", json={"handle": "Bad Handle!", "kind": "conductor"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_room_404(client):
    resp = await client.post(
        "/api/rooms/nope/engines", json={"handle": "conductor", "kind": "conductor"}
    )
    assert resp.status_code == 404
