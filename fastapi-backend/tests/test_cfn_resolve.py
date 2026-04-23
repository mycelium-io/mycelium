# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
Tests for CFN identifier resolution (workspace_id, mas_id).

The resolve helpers allow clients to omit workspace_id/mas_id and have the
backend resolve them from room context or settings fallbacks.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Room

pytestmark = pytest.mark.asyncio


# ── resolve_workspace_id ──────────────────────────────────────────────────────


async def test_resolve_workspace_id_from_client_value(client: AsyncClient, monkeypatch):
    """Client-provided workspace_id takes priority over settings."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_ENABLED", False)

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "workspace_id": "client-ws",
            "mas_id": "client-mas",
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 200
    # Ingest is disabled but we still verify resolution happened (no 400)


async def test_resolve_workspace_id_from_settings(client: AsyncClient, monkeypatch):
    """Falls back to settings.WORKSPACE_ID when client omits it."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_ENABLED", False)

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "mas_id": "client-mas",
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 200


async def test_resolve_workspace_id_400_when_unset(client: AsyncClient, monkeypatch):
    """Returns 400 when workspace_id is neither provided nor configured."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "")
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "mas_id": "client-mas",
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 400
    assert "workspace_id" in resp.json()["detail"].lower()


# ── resolve_mas_id ────────────────────────────────────────────────────────────


async def test_resolve_mas_id_from_client_value(client: AsyncClient, monkeypatch):
    """Client-provided mas_id takes priority over room lookup and settings."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_ENABLED", False)

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "workspace_id": "client-ws",
            "mas_id": "client-mas",
            "room_name": "some-room",  # should be ignored when mas_id is provided
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 200


async def test_resolve_mas_id_from_room_lookup(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Resolves mas_id from room DB record when room_name is provided."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_ENABLED", False)

    room = Room(name="test-room", mas_id="room-mas-id", workspace_id="room-ws-id")
    db_session.add(room)
    await db_session.commit()

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "room_name": "test-room",
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 200


async def test_resolve_mas_id_from_parent_namespace(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Session sub-rooms inherit mas_id from parent namespace."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "")  # no fallback
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_ENABLED", False)

    parent = Room(
        name="parent-ns",
        mas_id="parent-mas-id",
        workspace_id="parent-ws-id",
        is_namespace=True,
    )
    db_session.add(parent)
    await db_session.flush()

    child = Room(
        name="parent-ns:session:abc",
        mas_id=None,  # session doesn't have its own mas_id
        workspace_id="parent-ws-id",
        parent_namespace="parent-ns",
    )
    db_session.add(child)
    await db_session.commit()

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "room_name": "parent-ns:session:abc",
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 200


async def test_resolve_mas_id_room_exists_no_mas_id_falls_back_to_settings(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Room exists but has no mas_id; falls back to settings.MAS_ID."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_ENABLED", False)

    room = Room(name="orphan-room", mas_id=None, workspace_id="ws")
    db_session.add(room)
    await db_session.commit()

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "room_name": "orphan-room",
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 200


async def test_resolve_mas_id_room_not_found_400(client: AsyncClient, monkeypatch):
    """Returns 400 when room_name is provided but room doesn't exist."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "room_name": "nonexistent-room",
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


async def test_resolve_mas_id_room_exists_no_mas_id_no_settings_400(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Room exists but has no mas_id and settings.MAS_ID is unset; returns 400."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "")

    room = Room(name="orphan-room", mas_id=None, workspace_id="ws")
    db_session.add(room)
    await db_session.commit()

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "room_name": "orphan-room",
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 400
    assert "no mas_id" in resp.json()["detail"].lower()


async def test_resolve_mas_id_from_settings_fallback(client: AsyncClient, monkeypatch):
    """Falls back to settings.MAS_ID when no room_name and no client mas_id."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_ENABLED", False)

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 200


async def test_resolve_mas_id_400_when_nothing_available(client: AsyncClient, monkeypatch):
    """Returns 400 when mas_id cannot be resolved from any source."""
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    monkeypatch.setattr("app.config.settings.MAS_ID", "")

    resp = await client.post(
        "/api/knowledge/ingest",
        json={
            "records": [{"response": "test"}],
        },
    )
    assert resp.status_code == 400
    assert "cannot resolve mas_id" in resp.json()["detail"].lower()


# ── Direct tests of resolve helpers ───────────────────────────────────────────


async def test_resolve_helpers_direct(db_session: AsyncSession, monkeypatch):
    """Direct unit tests for the resolve helper functions."""
    from app.services.cfn_resolve import resolve_mas_id, resolve_workspace_id

    # resolve_workspace_id: client value wins
    assert resolve_workspace_id("client-ws") == "client-ws"

    # resolve_workspace_id: settings fallback
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "settings-ws")
    assert resolve_workspace_id(None) == "settings-ws"
    assert resolve_workspace_id("") == "settings-ws"

    # resolve_mas_id: client value wins
    mas = await resolve_mas_id("client-mas", None, db_session)
    assert mas == "client-mas"

    # resolve_mas_id: settings fallback when no room
    monkeypatch.setattr("app.config.settings.MAS_ID", "settings-mas")
    mas = await resolve_mas_id(None, None, db_session)
    assert mas == "settings-mas"
