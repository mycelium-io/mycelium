# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for /api/knowledge/ingest gates: disabled, refused, deduped, ok, error."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.services.cfn_knowledge import CfnKnowledgeError
from app.services.ingest_dedupe import get_cache
from app.services.ingest_log_buffer import get_buffer

pytestmark = pytest.mark.asyncio


INGEST_BODY = {
    "workspace_id": "ws-1",
    "mas_id": "mas-a",
    "agent_id": "alice",
    "records": [{"schema": "openclaw-conversation-v1", "turns": [{"userMessage": "hi"}]}],
}


@pytest.fixture(autouse=True)
def _reset_state():
    get_cache().clear()
    get_buffer().clear()
    yield
    get_cache().clear()
    get_buffer().clear()


@pytest.fixture()
def mock_cfn(monkeypatch):
    """Replace the CFN client with a success-returning AsyncMock."""
    mock = AsyncMock(return_value={"response_id": "cfn-rid-xyz", "message": "ok"})
    monkeypatch.setattr(
        "app.routes.knowledge.create_or_update_shared_memories",
        mock,
    )
    return mock


# ── Gate: happy path forwards to CFN ───────────────────────────────────────────


async def test_ingest_ok_forwards_to_cfn(client: AsyncClient, mock_cfn):
    resp = await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["cfn_response_id"] == "cfn-rid-xyz"
    assert body["cfn_message"] == "ok"
    assert body["estimated_cfn_knowledge_input_tokens"] > 0
    assert mock_cfn.await_count == 1

    events = get_buffer().snapshot()
    assert len(events) == 1
    assert events[0].state == "ok"
    assert events[0].cfn_status == 201


# ── Gate 1: disabled master switch ─────────────────────────────────────────────


async def test_ingest_disabled_short_circuits(client: AsyncClient, mock_cfn, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_ENABLED", False)
    resp = await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert "disabled" in (body.get("cfn_message") or "").lower()
    assert mock_cfn.await_count == 0

    events = get_buffer().snapshot()
    assert len(events) == 1
    assert events[0].state == "disabled"
    assert events[0].reason is not None


# ── Gate 2: token circuit breaker ──────────────────────────────────────────────


async def test_ingest_refused_above_token_threshold(
    client: AsyncClient,
    mock_cfn,
    monkeypatch,
):
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_MAX_INPUT_TOKENS", 5)
    resp = await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    assert resp.status_code == 413
    assert "exceeded" in resp.json()["detail"]
    assert mock_cfn.await_count == 0

    events = get_buffer().snapshot()
    assert len(events) == 1
    assert events[0].state == "refused"
    assert "5 estimated input tokens" in (events[0].reason or "")


async def test_ingest_zero_threshold_disables_circuit_breaker(
    client: AsyncClient,
    mock_cfn,
    monkeypatch,
):
    """max_input_tokens=0 means no limit — large payloads go through."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_MAX_INPUT_TOKENS", 0)
    big_body = {**INGEST_BODY, "records": [{"turns": ["x" * 10_000]}]}
    resp = await client.post("/api/knowledge/ingest", json=big_body)
    assert resp.status_code == 200
    assert mock_cfn.await_count == 1


# ── Gate 3: content-hash dedupe ────────────────────────────────────────────────


async def test_ingest_deduped_on_identical_payload(
    client: AsyncClient,
    mock_cfn,
):
    resp1 = await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    assert resp1.status_code == 200
    assert resp1.json()["cfn_response_id"] == "cfn-rid-xyz"
    assert mock_cfn.await_count == 1

    resp2 = await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    assert resp2.status_code == 200
    assert resp2.json()["cfn_response_id"] == "cfn-rid-xyz"  # same cached id
    assert mock_cfn.await_count == 1  # CFN not re-called

    events = get_buffer().snapshot()
    assert [e.state for e in events] == ["ok", "deduped"]
    assert events[1].reason is not None and "TTL" in events[1].reason


async def test_ingest_not_deduped_when_ttl_zero(
    client: AsyncClient,
    mock_cfn,
    monkeypatch,
):
    monkeypatch.setattr("app.config.settings.MYCELIUM_INGEST_DEDUPE_TTL_SECONDS", 0)

    await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    assert mock_cfn.await_count == 2  # both go through

    events = get_buffer().snapshot()
    assert [e.state for e in events] == ["ok", "ok"]


async def test_ingest_dedupe_distinguishes_different_payloads(
    client: AsyncClient,
    mock_cfn,
):
    await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    other = {**INGEST_BODY, "records": [{"turns": [{"userMessage": "bye"}]}]}
    await client.post("/api/knowledge/ingest", json=other)
    assert mock_cfn.await_count == 2  # different hash → both forwarded


# ── CFN failure path ──────────────────────────────────────────────────────────


async def test_ingest_cfn_error_logs_event_and_502s(
    client: AsyncClient,
    monkeypatch,
):
    fail = AsyncMock(side_effect=CfnKnowledgeError("CFN unreachable: boom"))
    monkeypatch.setattr("app.routes.knowledge.create_or_update_shared_memories", fail)

    resp = await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    assert resp.status_code == 502

    events = get_buffer().snapshot()
    assert len(events) == 1
    assert events[0].state == "error"
    assert "boom" in (events[0].reason or "")


async def test_ingest_cfn_http_status_error_preserves_code(
    client: AsyncClient,
    monkeypatch,
):
    fail = AsyncMock(side_effect=CfnKnowledgeError("CFN returned 503: down", status_code=503))
    monkeypatch.setattr("app.routes.knowledge.create_or_update_shared_memories", fail)

    resp = await client.post("/api/knowledge/ingest", json=INGEST_BODY)
    assert resp.status_code == 503
