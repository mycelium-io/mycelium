# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Unit tests for the in-process metrics store.

Guards the key invariants introduced by feat/simple_metrics:
  * @_safe logs warnings instead of silently swallowing errors
  * Token keys are normalised to input_tokens/output_tokens across
    both the ``llm`` and ``cfn_llm`` namespaces
  * record_consensus tracks per-room completion
  * record_coordination_round tracks round_num histogram
  * record_synthesis supports the ``skipped`` signal
"""

from __future__ import annotations

import logging

import pytest

from app.services.metrics import (
    _counters,
    _histograms,
    _lock,
    record_cfn_llm_usage,
    record_consensus,
    record_coordination_round,
    record_synthesis,
    snapshot,
)


def _reset_metrics() -> None:
    """Clear all counters and histograms between tests."""
    with _lock:
        _counters.clear()
        _histograms.clear()


# ── @_safe logging ────────────────────────────────────────────────────


def test_safe_decorator_logs_warning_on_bad_input(caplog: pytest.LogCaptureFixture) -> None:
    """@_safe must log at WARNING, not DEBUG, so bad data is visible."""
    _reset_metrics()
    with caplog.at_level(logging.WARNING, logger="app.services.metrics"):
        record_cfn_llm_usage(
            operation="test",
            prompt_tokens="not_an_int",
        )
    assert any("metrics.record_cfn_llm_usage failed" in r.message for r in caplog.records)


# ── cfn_llm normalised keys ──────────────────────────────────────────


def test_cfn_llm_uses_input_output_keys() -> None:
    """cfn_llm namespace must store input_tokens/output_tokens, not prompt/completion."""
    _reset_metrics()
    record_cfn_llm_usage(
        operation="start_negotiation",
        room="room-1",
        prompt_tokens=100,
        completion_tokens=50,
        cached_tokens=10,
        total_tokens=160,
        llm_calls=2,
        latency_ms=500.0,
    )

    snap = snapshot()
    cfn_llm = snap["counters"]["cfn_llm"]

    assert cfn_llm["input_tokens"] == 100
    assert cfn_llm["output_tokens"] == 50
    assert cfn_llm["cached_tokens"] == 10
    assert cfn_llm["calls"] == 2
    assert "prompt_tokens" not in cfn_llm
    assert "completion_tokens" not in cfn_llm

    assert cfn_llm["by_room.room-1.input_tokens"] == 100
    assert cfn_llm["by_room.room-1.output_tokens"] == 50
    assert "by_room.room-1.prompt_tokens" not in cfn_llm


def test_cfn_llm_by_operation_uses_normalised_keys() -> None:
    """by_operation and by_pipeline sub-keys must also be normalised."""
    _reset_metrics()
    record_cfn_llm_usage(
        operation="start_negotiation",
        prompt_tokens=0,
        completion_tokens=0,
        llm_calls=0,
        by_operation={
            "semantic_negotiation.classify": {
                "prompt_tokens": 200,
                "completion_tokens": 80,
                "calls": 3,
            },
        },
    )

    snap = snapshot()
    cfn_llm = snap["counters"]["cfn_llm"]

    assert cfn_llm["by_llm_operation.semantic_negotiation.classify.input_tokens"] == 200
    assert cfn_llm["by_llm_operation.semantic_negotiation.classify.output_tokens"] == 80
    assert cfn_llm["by_pipeline.semantic_negotiation.input_tokens"] == 200
    assert cfn_llm["by_pipeline.semantic_negotiation.output_tokens"] == 80


# ── record_consensus room tracking ───────────────────────────────────


def test_record_consensus_tracks_room() -> None:
    """record_consensus must record per-room completion and outcome."""
    _reset_metrics()
    record_consensus(room="room-alpha", total_rounds=5, outcome="success")
    record_consensus(room="room-alpha", total_rounds=3, outcome="failure")

    snap = snapshot()
    coord = snap["counters"]["coordination"]

    assert coord["sessions_completed"] == 2
    assert coord["completed_by_room.room-alpha"] == 2
    assert coord["completed_by_room.room-alpha.success"] == 1
    assert coord["completed_by_room.room-alpha.failure"] == 1


# ── record_coordination_round round_num ──────────────────────────────


def test_record_coordination_round_tracks_round_num() -> None:
    """round_num must be recorded as a histogram."""
    _reset_metrics()
    record_coordination_round(room="room-1", round_num=3, participants=2, duration_ms=100)

    snap = snapshot()
    assert "coordination.round_num" in snap["histograms"]
    h = snap["histograms"]["coordination.round_num"]
    assert h["count"] == 1
    assert h["min"] == 3.0
    assert h["max"] == 3.0


# ── record_synthesis skipped ─────────────────────────────────────────


def test_record_synthesis_skipped_increments_counter() -> None:
    """Skipped synthesis must bump runs + skipped counters, not errors."""
    _reset_metrics()
    record_synthesis(skipped="no_memories")
    record_synthesis(skipped="needs_reindex")
    record_synthesis(duration_ms=1000.0)

    snap = snapshot()
    synth = snap["counters"]["synthesis"]

    assert synth["runs"] == 3
    assert synth["skipped"] == 2
    assert synth["skipped.no_memories"] == 1
    assert synth["skipped.needs_reindex"] == 1
    assert "errors" not in synth


def test_record_synthesis_error_records_duration() -> None:
    """Error synthesis must still appear in the duration histogram."""
    _reset_metrics()
    record_synthesis(duration_ms=500.0, error=True)

    snap = snapshot()
    assert snap["counters"]["synthesis"]["errors"] == 1
    assert "synthesis.duration_ms" in snap["histograms"]
    assert snap["histograms"]["synthesis.duration_ms"]["count"] == 1
