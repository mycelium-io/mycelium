# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for /api/internal/audit-events endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

VALID_PAYLOAD = {
    "resource_type": "MAS",
    "resource_identifier": "mas-abc123",
    "audit_type": "RESOURCE_CREATED",
    "audit_resource_identifier": "agent-xyz",
    "created_by": "00000000-0000-0000-0000-000000000001",
    "last_modified_by": "00000000-0000-0000-0000-000000000001",
}


async def test_create_audit_event(client: AsyncClient):
    resp = await client.post("/api/internal/audit-events", json=VALID_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json() == {"message": "entry created"}


async def test_create_audit_event_invalid_resource_type(client: AsyncClient):
    payload = {**VALID_PAYLOAD, "resource_type": "NOT_A_THING"}
    resp = await client.post("/api/internal/audit-events", json=payload)
    assert resp.status_code == 400
    assert "resource_type" in resp.json()["detail"]


async def test_create_audit_event_invalid_audit_type(client: AsyncClient):
    payload = {**VALID_PAYLOAD, "audit_type": "MADE_UP"}
    resp = await client.post("/api/internal/audit-events", json=payload)
    assert resp.status_code == 400
    assert "audit_type" in resp.json()["detail"]


async def test_list_audit_events_empty(client: AsyncClient):
    resp = await client.get("/api/internal/audit-events")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_audit_events(client: AsyncClient):
    await client.post("/api/internal/audit-events", json=VALID_PAYLOAD)
    await client.post(
        "/api/internal/audit-events", json={**VALID_PAYLOAD, "resource_type": "WORKFLOW"}
    )

    resp = await client.get("/api/internal/audit-events")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_list_audit_events_filter_resource_type(client: AsyncClient):
    await client.post("/api/internal/audit-events", json=VALID_PAYLOAD)
    await client.post(
        "/api/internal/audit-events", json={**VALID_PAYLOAD, "resource_type": "WORKFLOW"}
    )

    resp = await client.get("/api/internal/audit-events", params={"resource_type": "MAS"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["resource_type"] == "MAS"


async def test_list_audit_events_filter_audit_type(client: AsyncClient):
    await client.post("/api/internal/audit-events", json=VALID_PAYLOAD)
    await client.post(
        "/api/internal/audit-events", json={**VALID_PAYLOAD, "audit_type": "RESOURCE_DELETED"}
    )

    resp = await client.get("/api/internal/audit-events", params={"audit_type": "RESOURCE_DELETED"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["audit_type"] == "RESOURCE_DELETED"


async def test_list_audit_events_invalid_filter(client: AsyncClient):
    resp = await client.get("/api/internal/audit-events", params={"resource_type": "NOPE"})
    assert resp.status_code == 400


async def test_get_audit_event(client: AsyncClient):
    await client.post("/api/internal/audit-events", json=VALID_PAYLOAD)
    events = (await client.get("/api/internal/audit-events")).json()
    event_id = events[0]["id"]

    resp = await client.get(f"/api/internal/audit-events/{event_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == event_id
    assert resp.json()["resource_type"] == "MAS"


async def test_get_audit_event_not_found(client: AsyncClient):
    resp = await client.get("/api/internal/audit-events/00000000-0000-0000-0000-000000000099")
    assert resp.status_code == 404


async def test_delete_audit_event(client: AsyncClient):
    await client.post("/api/internal/audit-events", json=VALID_PAYLOAD)
    events = (await client.get("/api/internal/audit-events")).json()
    event_id = events[0]["id"]

    resp = await client.delete(f"/api/internal/audit-events/{event_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/internal/audit-events/{event_id}")
    assert resp.status_code == 404


async def test_delete_audit_event_not_found(client: AsyncClient):
    resp = await client.delete("/api/internal/audit-events/00000000-0000-0000-0000-000000000099")
    assert resp.status_code == 404


async def test_create_with_optional_fields(client: AsyncClient):
    payload = {
        **VALID_PAYLOAD,
        "operation_id": "op-abc",
        "audit_information": {"key": "value", "count": 3},
        "audit_extra_information": "some extra text",
    }
    resp = await client.post("/api/internal/audit-events", json=payload)
    assert resp.status_code == 200

    events = (await client.get("/api/internal/audit-events")).json()
    assert events[0]["operation_id"] == "op-abc"
    assert events[0]["audit_information"] == {"key": "value", "count": 3}
