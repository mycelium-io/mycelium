# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for the per-agent memory-operations CFN proxy.

CFN shared-memories read-surface tests live in test_cfn_read_surface.py.
"""

from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent

pytestmark = pytest.mark.asyncio

_FAKE_WS_ID = "00000000-0000-0000-0000-000000000001"
_FAKE_MAS_ID = "00000000-0000-0000-0000-000000000002"


async def _create_agent(
    db: AsyncSession,
    mem_url: str = "http://mem-provider",
) -> Agent:
    agent = Agent(mas_id=uuid4(), name="agent1", memory_provider_url=mem_url)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


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
