# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for /api/internal/coordination/* endpoints (#162).

CI-safe: drives the trace ring buffer directly via the service module, then
asserts the HTTP layer surfaces the same data.  No real CFN, no DB, no
network.
"""

import pytest
from httpx import AsyncClient

from app.services import coordination as coord

pytestmark = pytest.mark.asyncio


def _push_trace(room: str, *, synthesised_handles: list[str] | None = None) -> None:
    """Helper: push one closed trace into the ring buffer."""
    per_agent = {
        h: coord._PerAgentTrace(handle=h, was_synthesised=h in (synthesised_handles or []))
        for h in ["alice", "bob"]
    }
    trace = coord._RoundTrace(
        room_name=room,
        session_id=f"sess-{room}",
        mas_id="mas",
        workspace_id="ws",
        round_n=0,
        n_agents=2,
        per_agent=per_agent,
    )
    trace.decision_path = "watchdog_fired" if synthesised_handles else "all_replied"
    trace.outcome = "ongoing" if synthesised_handles else "agreed"
    trace.closed_at = trace.started_at
    coord._emit_round_trace(trace)


async def test_list_round_traces_returns_buffer_contents(client: AsyncClient):
    coord.clear_round_traces()
    _push_trace("room-a")
    _push_trace("room-b", synthesised_handles=["bob"])

    resp = await client.get("/api/internal/coordination/round-traces")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["buffer_capacity"] == coord.ROUND_TRACE_BUFFER_SIZE
    rooms = [t["room"] for t in body["traces"]]
    assert rooms == ["room-a", "room-b"]
    assert body["traces"][1]["synthesised_count"] == 1
    assert body["traces"][1]["synthesised_handles"] == ["bob"]
    assert body["traces"][1]["decision_path"] == "watchdog_fired"

    coord.clear_round_traces()


async def test_list_round_traces_respects_limit_query(client: AsyncClient):
    coord.clear_round_traces()
    for i in range(5):
        _push_trace(f"room-{i}")

    resp = await client.get("/api/internal/coordination/round-traces?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert [t["room"] for t in body["traces"]] == ["room-3", "room-4"]

    coord.clear_round_traces()


async def test_list_round_traces_empty_buffer(client: AsyncClient):
    coord.clear_round_traces()
    resp = await client.get("/api/internal/coordination/round-traces")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["traces"] == []


async def test_clear_round_traces_empties_buffer(client: AsyncClient):
    coord.clear_round_traces()
    _push_trace("room-x")
    _push_trace("room-y")
    assert len(coord.get_round_traces()) == 2

    resp = await client.delete("/api/internal/coordination/round-traces")
    assert resp.status_code == 204
    assert coord.get_round_traces() == []


async def test_list_round_traces_rejects_negative_limit(client: AsyncClient):
    resp = await client.get("/api/internal/coordination/round-traces?limit=-1")
    # FastAPI Query(ge=0) returns 422 for out-of-range values.
    assert resp.status_code == 422
