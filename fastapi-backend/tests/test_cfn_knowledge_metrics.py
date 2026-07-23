# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for CFN knowledge-query cost tracking.

``shared-memories/query``'s response schema declares an optional ``meta``
field ("LLM token usage... present when LLM calls are made") that was
previously read nowhere — its evidence-agent LLM cost was invisible to
``mycelium metrics show cost`` even though the data was on the wire.
"""

from __future__ import annotations

import pytest

from app.services.cfn_knowledge import _record_query_meta_usage
from app.services.metrics import _counters, _lock, _room_identities, record_room_identity, snapshot


def _reset_metrics() -> None:
    with _lock:
        _counters.clear()
        _room_identities.clear()


def test_query_meta_usage_recorded() -> None:
    _reset_metrics()
    _record_query_meta_usage(
        {
            "tokens": {"prompt": 500, "completion": 120, "total": 620},
            "latency_ms": 340.0,
        }
    )
    cfn_llm = snapshot()["counters"]["cfn_llm"]
    assert cfn_llm["input_tokens"] == 500
    assert cfn_llm["output_tokens"] == 120
    assert cfn_llm["total_tokens"] == 620
    assert cfn_llm["calls"] == 1
    assert cfn_llm["by_pipeline.knowledge_query.input_tokens"] == 500
    assert cfn_llm["by_pipeline.knowledge_query.output_tokens"] == 120


def test_query_meta_usage_absent_is_a_noop() -> None:
    """CFN's meta is optional (only present when the evidence agent makes an
    LLM call) — no meta, or an all-zero one, must not fabricate a counter."""
    _reset_metrics()
    _record_query_meta_usage(None)
    _record_query_meta_usage({})
    _record_query_meta_usage({"tokens": {"prompt": 0, "completion": 0, "total": 0}})
    assert "cfn_llm" not in snapshot()["counters"]


def test_query_meta_usage_resolves_room_via_mas_id() -> None:
    """When the mas_id -> room mapping was already learned (e.g. via an
    earlier negotiation call), the knowledge-query breakdown should reuse it
    rather than requiring every caller to thread a room name through."""
    _reset_metrics()
    record_room_identity(mas_id="mas-42", room_name="my-room")
    _record_query_meta_usage(
        {"tokens": {"prompt": 100, "completion": 20, "total": 120}},
        mas_id="mas-42",
    )
    cfn_llm = snapshot()["counters"]["cfn_llm"]
    assert cfn_llm["by_room.my-room.input_tokens"] == 100
    assert cfn_llm["by_room.my-room.output_tokens"] == 20


def test_query_meta_usage_unknown_mas_id_skips_room_breakdown() -> None:
    """No mapping learned yet — must not raise, and must not fabricate a room."""
    _reset_metrics()
    _record_query_meta_usage(
        {"tokens": {"prompt": 100, "completion": 20, "total": 120}},
        mas_id="never-seen",
    )
    cfn_llm = snapshot()["counters"]["cfn_llm"]
    assert cfn_llm["input_tokens"] == 100
    assert not any(k.startswith("by_room.") for k in cfn_llm)


@pytest.mark.asyncio
async def test_query_shared_memories_records_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    """The full query_shared_memories call records the response's meta."""
    from app.services import cfn_knowledge

    _reset_metrics()

    async def _fake_cfn_post(url, body, *, operation):
        return {
            "response_id": "r-1",
            "message": "answer",
            "meta": {"tokens": {"prompt": 10, "completion": 5, "total": 15}},
        }

    monkeypatch.setattr(cfn_knowledge, "_cfn_post", _fake_cfn_post)

    await cfn_knowledge.query_shared_memories(
        workspace_id="ws-1", mas_id="mas-1", intent="what changed?"
    )

    cfn_llm = snapshot()["counters"]["cfn_llm"]
    assert cfn_llm["input_tokens"] == 10
    assert cfn_llm["output_tokens"] == 5
