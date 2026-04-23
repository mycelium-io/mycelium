# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Tests for /api/cfn/knowledge/* — the CFN shared-memories read proxy."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.services.cfn_knowledge import CfnKnowledgeError

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _set_default_workspace(monkeypatch):
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "ws-default")
    monkeypatch.setattr("app.config.settings.MAS_ID", "mas-default")


# ── /api/cfn/knowledge/query ───────────────────────────────────────────────────


async def test_query_forwards_intent_to_cfn(client: AsyncClient, monkeypatch):
    mock = AsyncMock(
        return_value={"response_id": "r-1", "message": "the website_selector picks websites"},
    )
    monkeypatch.setattr("app.routes.cfn_proxy.query_shared_memories", mock)

    resp = await client.post(
        "/api/cfn/knowledge/query",
        json={"mas_id": "mas-a", "intent": "what does the selector do?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "the website_selector picks websites"

    call = mock.await_args.kwargs
    assert call["workspace_id"] == "ws-default"
    assert call["mas_id"] == "mas-a"
    assert call["intent"] == "what does the selector do?"
    assert call["search_strategy"] == "semantic_graph_traversal"


async def test_query_uses_explicit_workspace_over_default(
    client: AsyncClient,
    monkeypatch,
):
    mock = AsyncMock(return_value={"response_id": "r", "message": "ok"})
    monkeypatch.setattr("app.routes.cfn_proxy.query_shared_memories", mock)

    await client.post(
        "/api/cfn/knowledge/query",
        json={
            "workspace_id": "ws-override",
            "mas_id": "mas-a",
            "intent": "anything",
        },
    )
    assert mock.await_args.kwargs["workspace_id"] == "ws-override"


async def test_query_resolves_mas_id_from_settings_when_omitted(
    client: AsyncClient,
    monkeypatch,
):
    """Leaf nodes can omit mas_id; backend resolves from settings.MAS_ID."""
    mock = AsyncMock(return_value={"response_id": "r", "message": "ok"})
    monkeypatch.setattr("app.routes.cfn_proxy.query_shared_memories", mock)

    resp = await client.post(
        "/api/cfn/knowledge/query",
        json={"intent": "anything"},
    )
    assert resp.status_code == 200
    call = mock.await_args.kwargs
    assert call["workspace_id"] == "ws-default"
    assert call["mas_id"] == "mas-default"


async def test_query_400_when_no_mas_id_and_no_default(
    client: AsyncClient,
    monkeypatch,
):
    monkeypatch.setattr("app.config.settings.MAS_ID", "")
    resp = await client.post(
        "/api/cfn/knowledge/query",
        json={"intent": "anything"},
    )
    assert resp.status_code == 400
    assert "mas_id" in resp.json()["detail"].lower()


async def test_query_400_when_no_workspace_and_no_default(
    client: AsyncClient,
    monkeypatch,
):
    monkeypatch.setattr("app.config.settings.WORKSPACE_ID", "")
    resp = await client.post(
        "/api/cfn/knowledge/query",
        json={"mas_id": "mas-a", "intent": "huh"},
    )
    assert resp.status_code == 400
    assert "workspace_id" in resp.json()["detail"]


async def test_query_surfaces_cfn_error_status(client: AsyncClient, monkeypatch):
    fail = AsyncMock(
        side_effect=CfnKnowledgeError("CFN returned 404: not found", status_code=404),
    )
    monkeypatch.setattr("app.routes.cfn_proxy.query_shared_memories", fail)
    resp = await client.post(
        "/api/cfn/knowledge/query",
        json={"mas_id": "mas-a", "intent": "anything"},
    )
    assert resp.status_code == 404


async def test_query_502_on_transport_error(client: AsyncClient, monkeypatch):
    fail = AsyncMock(side_effect=CfnKnowledgeError("CFN unreachable: boom"))
    monkeypatch.setattr("app.routes.cfn_proxy.query_shared_memories", fail)
    resp = await client.post(
        "/api/cfn/knowledge/query",
        json={"mas_id": "mas-a", "intent": "anything"},
    )
    assert resp.status_code == 502


# ── /api/cfn/knowledge/concepts ────────────────────────────────────────────────


async def test_concepts_by_ids(client: AsyncClient, monkeypatch):
    mock = AsyncMock(
        return_value={
            "records": [
                {"concepts": [{"id": "c1", "name": "Website"}], "relationships": []},
            ],
        },
    )
    monkeypatch.setattr("app.routes.cfn_proxy.get_concepts_by_ids", mock)

    resp = await client.post(
        "/api/cfn/knowledge/concepts",
        json={"mas_id": "mas-a", "ids": ["c1", "c2"]},
    )
    assert resp.status_code == 200
    assert resp.json()["records"][0]["concepts"][0]["id"] == "c1"
    assert mock.await_args.kwargs["ids"] == ["c1", "c2"]


async def test_concepts_requires_non_empty_ids(client: AsyncClient):
    resp = await client.post(
        "/api/cfn/knowledge/concepts",
        json={"mas_id": "mas-a", "ids": []},
    )
    assert resp.status_code == 422


# ── /api/cfn/knowledge/concepts/{id}/neighbors ─────────────────────────────────


async def test_concept_neighbors(client: AsyncClient, monkeypatch):
    mock = AsyncMock(
        return_value={
            "records": [{"concepts": [{"id": "n1", "name": "related"}], "relationships": []}],
        },
    )
    monkeypatch.setattr("app.routes.cfn_proxy.get_concept_neighbors", mock)

    resp = await client.get(
        "/api/cfn/knowledge/concepts/c1/neighbors",
        params={"mas_id": "mas-a"},
    )
    assert resp.status_code == 200
    call = mock.await_args.kwargs
    assert call["workspace_id"] == "ws-default"
    assert call["mas_id"] == "mas-a"
    assert call["concept_id"] == "c1"


async def test_concept_neighbors_explicit_workspace(client: AsyncClient, monkeypatch):
    mock = AsyncMock(return_value={"records": []})
    monkeypatch.setattr("app.routes.cfn_proxy.get_concept_neighbors", mock)
    await client.get(
        "/api/cfn/knowledge/concepts/c1/neighbors",
        params={"mas_id": "mas-a", "workspace_id": "ws-override"},
    )
    assert mock.await_args.kwargs["workspace_id"] == "ws-override"


# ── /api/cfn/knowledge/paths ───────────────────────────────────────────────────


async def test_paths(client: AsyncClient, monkeypatch):
    mock = AsyncMock(return_value={"paths": [{"from": "c1", "to": "c2", "hops": ["r1"]}]})
    monkeypatch.setattr("app.routes.cfn_proxy.get_graph_paths", mock)

    resp = await client.post(
        "/api/cfn/knowledge/paths",
        json={
            "mas_id": "mas-a",
            "source_id": "c1",
            "target_id": "c2",
            "max_depth": 3,
            "limit": 5,
        },
    )
    assert resp.status_code == 200
    call = mock.await_args.kwargs
    assert call["source_id"] == "c1"
    assert call["target_id"] == "c2"
    assert call["max_depth"] == 3
    assert call["limit"] == 5


async def test_paths_optional_args_omitted_when_unset(client: AsyncClient, monkeypatch):
    mock = AsyncMock(return_value={"paths": []})
    monkeypatch.setattr("app.routes.cfn_proxy.get_graph_paths", mock)

    await client.post(
        "/api/cfn/knowledge/paths",
        json={"mas_id": "mas-a", "source_id": "c1", "target_id": "c2"},
    )
    call = mock.await_args.kwargs
    assert call["max_depth"] is None
    assert call["relations"] is None
    assert call["limit"] is None
