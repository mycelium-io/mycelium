# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Tests for the in-memory CFN ingest log buffer and its GET endpoints."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.services.ingest_log_buffer import IngestEvent, get_buffer

pytestmark = pytest.mark.asyncio


def _event(
    *,
    mas_id: str = "mas-a",
    agent_id: str | None = "alice",
    tokens: int = 50,
    payload_bytes: int = 100,
    request_id: str = "req-1",
    cfn_status: int | None = 201,
    state: str = "ok",
    reason: str | None = None,
    timestamp: datetime | None = None,
) -> IngestEvent:
    return IngestEvent(
        timestamp=timestamp or datetime.now(UTC),
        workspace_id="ws-1",
        mas_id=mas_id,
        agent_id=agent_id,
        request_id=request_id,
        record_count=1,
        payload_bytes=payload_bytes,
        estimated_cfn_knowledge_input_tokens=tokens,
        latency_ms=12.3,
        state=state,  # type: ignore[arg-type]
        reason=reason,
        cfn_status=cfn_status,
    )


# ── unit tests on the buffer itself ────────────────────────────────────────────


async def test_buffer_append_and_snapshot():
    buf = get_buffer()
    buf.clear()
    buf.append(_event(request_id="a"))
    buf.append(_event(request_id="b"))
    snap = buf.snapshot()
    assert [e.request_id for e in snap] == ["a", "b"]


async def test_buffer_maxlen_drops_oldest():
    from app.services.ingest_log_buffer import IngestLogBuffer

    buf = IngestLogBuffer(maxlen=3)
    for i in range(5):
        buf.append(_event(request_id=f"req-{i}"))
    snap = buf.snapshot()
    assert [e.request_id for e in snap] == ["req-2", "req-3", "req-4"]


# ── GET /api/knowledge/ingest/log ──────────────────────────────────────────────


async def test_ingest_log_empty(client: AsyncClient):
    get_buffer().clear()
    resp = await client.get("/api/knowledge/ingest/log")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_events"] == 0
    assert body["events"] == []
    assert "buffer_started_at" in body


async def test_ingest_log_newest_first_and_limit(client: AsyncClient):
    buf = get_buffer()
    buf.clear()
    for i in range(5):
        buf.append(_event(request_id=f"req-{i}"))

    resp = await client.get("/api/knowledge/ingest/log?limit=3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_events"] == 5
    assert [e["request_id"] for e in body["events"]] == ["req-4", "req-3", "req-2"]


async def test_ingest_log_limit_bounds(client: AsyncClient):
    get_buffer().clear()
    resp = await client.get("/api/knowledge/ingest/log?limit=0")
    assert resp.status_code == 422
    resp = await client.get("/api/knowledge/ingest/log?limit=501")
    assert resp.status_code == 422


# ── GET /api/knowledge/ingest/stats ────────────────────────────────────────────


async def test_ingest_stats_empty(client: AsyncClient):
    get_buffer().clear()
    resp = await client.get("/api/knowledge/ingest/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"]["events"] == 0
    assert body["total"]["estimated_cfn_knowledge_input_tokens"] == 0
    assert body["last_event_at"] is None
    assert body["by_mas"] == {}
    assert body["by_agent"] == {}


async def test_ingest_stats_aggregates_tokens_and_bytes(client: AsyncClient):
    buf = get_buffer()
    buf.clear()
    for i in range(3):
        buf.append(
            _event(
                request_id=f"req-{i}",
                tokens=50 * (i + 1),
                payload_bytes=100 * (i + 1),
            ),
        )
    resp = await client.get("/api/knowledge/ingest/stats")
    body = resp.json()
    assert body["total"]["events"] == 3
    assert body["total"]["estimated_cfn_knowledge_input_tokens"] == 300
    assert body["total"]["payload_bytes"] == 600


async def test_ingest_stats_by_mas_and_agent(client: AsyncClient):
    buf = get_buffer()
    buf.clear()
    buf.append(_event(mas_id="mas-a", agent_id="alice", tokens=10))
    buf.append(_event(mas_id="mas-a", agent_id="alice", tokens=20))
    buf.append(_event(mas_id="mas-b", agent_id="bob", tokens=30))
    buf.append(_event(mas_id="mas-b", agent_id=None, tokens=40))

    resp = await client.get("/api/knowledge/ingest/stats")
    body = resp.json()

    assert body["by_mas"]["mas-a"]["events"] == 2
    assert body["by_mas"]["mas-a"]["estimated_cfn_knowledge_input_tokens"] == 30
    assert body["by_mas"]["mas-b"]["events"] == 2
    assert body["by_mas"]["mas-b"]["estimated_cfn_knowledge_input_tokens"] == 70

    assert body["by_agent"]["alice"]["events"] == 2
    assert body["by_agent"]["bob"]["events"] == 1
    assert body["by_agent"]["(none)"]["events"] == 1


async def test_ingest_stats_last_hour_window(client: AsyncClient):
    buf = get_buffer()
    buf.clear()
    now = datetime.now(UTC)
    buf.append(_event(request_id="recent", timestamp=now, tokens=100))
    buf.append(
        _event(
            request_id="old",
            timestamp=now - timedelta(hours=2),
            tokens=999,
        ),
    )

    resp = await client.get("/api/knowledge/ingest/stats")
    body = resp.json()

    assert body["total"]["events"] == 2
    assert body["total"]["estimated_cfn_knowledge_input_tokens"] == 1099
    assert body["last_hour"]["events"] == 1
    assert body["last_hour"]["estimated_cfn_knowledge_input_tokens"] == 100


async def test_ingest_stats_last_event_at_matches_newest(client: AsyncClient):
    buf = get_buffer()
    buf.clear()
    t1 = datetime.now(UTC) - timedelta(minutes=5)
    t2 = datetime.now(UTC)
    buf.append(_event(request_id="first", timestamp=t1))
    buf.append(_event(request_id="second", timestamp=t2))

    resp = await client.get("/api/knowledge/ingest/stats")
    body = resp.json()
    assert body["last_event_at"] is not None
    assert body["last_event_at"].startswith(t2.isoformat()[:19])
