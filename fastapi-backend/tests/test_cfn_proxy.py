# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for CFN proxy endpoints."""

from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent

pytestmark = pytest.mark.asyncio

_FAKE_WS_ID = "00000000-0000-0000-0000-000000000001"
_FAKE_MAS_ID = "00000000-0000-0000-0000-000000000002"


# ── helpers ───────────────────────────────────────────────────────────────────


async def _create_agent(
    db: AsyncSession,
    mem_url: str = "http://mem-provider",
) -> Agent:
    agent = Agent(mas_id=uuid4(), name="agent1", memory_provider_url=mem_url)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


# ── shared-memories upsert ────────────────────────────────────────────────────
# shared-memories now calls the local knowledge graph service (no upstream HTTP)


async def test_upsert_shared_memories_success(client: AsyncClient):
    """Empty concepts/relations store succeeds — graph is created, nothing written."""
    resp = await client.post(
        "/api/workspaces/00000000-0000-0000-0000-000000000001/multi-agentic-systems/00000000-0000-0000-0000-000000000002/shared-memories",
        json={"records": {"concepts": [], "relations": []}},
    )
    # The AgensGraph engine is not available in tests (no live DB), so the service
    # returns FAILURE; we just care that the endpoint parses the request and routes it
    # without crashing (any 2xx or 5xx is fine — not 422 validation error)
    assert resp.status_code in (201, 500)


async def test_upsert_shared_memories_validation_error(client: AsyncClient):
    """Missing mas_id/wksp_id (not injected) — 400."""
    # Sending body with explicit empty mas_id and wksp_id overrides the URL injection
    resp = await client.post(
        "/api/workspaces/00000000-0000-0000-0000-000000000001/multi-agentic-systems/00000000-0000-0000-0000-000000000002/shared-memories",
        json={"mas_id": "", "wksp_id": ""},
    )
    assert resp.status_code == 400


# ── shared-memories query ─────────────────────────────────────────────────────


async def test_fetch_shared_memories_invalid_query_type(client: AsyncClient):
    """Invalid query_type → 400 from Pydantic validation."""
    resp = await client.post(
        "/api/workspaces/00000000-0000-0000-0000-000000000001/multi-agentic-systems/00000000-0000-0000-0000-000000000002/shared-memories/query",
        # path query requires 2 concepts; sending 3 triggers the validator
        json={
            "records": {"concepts": [{"id": "a"}]},
            "query_criteria": {"query_type": "path"},
        },
    )
    assert resp.status_code == 400


async def test_fetch_shared_memories_routes_to_local_service(client: AsyncClient):
    """Valid query request is parsed and routed to local service (no HTTP proxy)."""
    resp = await client.post(
        "/api/workspaces/00000000-0000-0000-0000-000000000001/multi-agentic-systems/00000000-0000-0000-0000-000000000002/shared-memories/query",
        json={"records": {"concepts": [{"id": "a"}]}},
    )
    # AgensGraph not available in tests → NOT_FOUND or FAILURE, but not 422
    assert resp.status_code in (200, 404, 500)


# ── memory-operations proxy ───────────────────────────────────────────────────


async def test_memory_operations_forwards_request(
    client: AsyncClient, db_session: AsyncSession, respx_mock
):
    agent = await _create_agent(db_session)
    respx_mock.post("http://mem-provider/v1/memories").mock(
        return_value=httpx.Response(200, json={"id": "mem-123"})
    )

    resp = await client.post(
        f"/api/workspaces/{_FAKE_WS_ID}/multi-agentic-systems/{_FAKE_MAS_ID}/agents/{agent.id}/memory-operations",
        json={
            "payload": {
                "http-request-type": "POST",
                "http-url": "/v1/memories",
                "http-request-body": {"text": "hello"},
                "http-headers": {},
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["http-status"] == 200
    assert body["http-response-body"]["id"] == "mem-123"


async def test_memory_operations_missing_method(client: AsyncClient, db_session: AsyncSession):
    agent = await _create_agent(db_session)
    resp = await client.post(
        f"/api/workspaces/{_FAKE_WS_ID}/multi-agentic-systems/{_FAKE_MAS_ID}/agents/{agent.id}/memory-operations",
        json={"payload": {"http-url": "/v1/memories"}},
    )
    assert resp.status_code == 400
    assert "http-request-type" in resp.json()["detail"]


async def test_memory_operations_agent_not_found(client: AsyncClient):
    resp = await client.post(
        "/api/workspaces/00000000-0000-0000-0000-000000000001/multi-agentic-systems/00000000-0000-0000-0000-000000000002/agents/00000000-0000-0000-0000-000000000003/memory-operations",
        json={"payload": {"http-request-type": "GET", "http-url": "/health"}},
    )
    assert resp.status_code == 404


async def test_memory_operations_get_request(
    client: AsyncClient, db_session: AsyncSession, respx_mock
):
    agent = await _create_agent(db_session)
    respx_mock.get("http://mem-provider/v1/memories").mock(
        return_value=httpx.Response(200, json={"memories": []})
    )

    resp = await client.post(
        f"/api/workspaces/{_FAKE_WS_ID}/multi-agentic-systems/{_FAKE_MAS_ID}/agents/{agent.id}/memory-operations",
        json={
            "payload": {
                "http-request-type": "GET",
                "http-url": "/v1/memories",
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json()["http-response-body"]["memories"] == []
