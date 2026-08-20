# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Unit tests for the in-process metrics store.

Guards the key invariants:
  * @_safe logs warnings instead of silently swallowing errors
  * Token keys are normalised to input_tokens/output_tokens in the
    ``llm`` namespace
"""

from __future__ import annotations

import logging

import pytest

from app.services.metrics import (
    _counters,
    _histograms,
    _lock,
    record_llm_call,
    snapshot,
)


def _reset_metrics() -> None:
    with _lock:
        _counters.clear()
        _histograms.clear()


# ── @_safe logging ────────────────────────────────────────────────────


def test_safe_decorator_logs_warning_on_bad_input(caplog: pytest.LogCaptureFixture) -> None:
    """@_safe must log at WARNING, not DEBUG, so bad data is visible."""
    _reset_metrics()
    with caplog.at_level(logging.WARNING, logger="app.services.metrics"):
        record_llm_call(
            operation="test",
            input_tokens="not_an_int",
        )
    assert any("metrics.record_llm_call failed" in r.message for r in caplog.records)


# ── llm normalised keys ──────────────────────────────────────────────


def test_llm_uses_input_output_keys() -> None:
    """llm namespace must store input_tokens/output_tokens, not prompt/completion."""
    _reset_metrics()
    record_llm_call(
        operation="start_negotiation",
        room="room-1",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.01,
        duration_ms=500.0,
    )

    snap = snapshot()
    llm = snap["counters"]["llm"]

    assert llm["input_tokens"] == 100
    assert llm["output_tokens"] == 50
    assert llm["calls"] == 1
    assert "prompt_tokens" not in llm
    assert "completion_tokens" not in llm

    assert llm["by_room.room-1.input_tokens"] == 100
    assert llm["by_room.room-1.output_tokens"] == 50
    assert "by_room.room-1.prompt_tokens" not in llm


def test_llm_latency_histogram() -> None:
    """duration_ms must be recorded as a histogram."""
    _reset_metrics()
    record_llm_call(operation="probe", input_tokens=1, output_tokens=1, duration_ms=100)

    snap = snapshot()
    assert "llm.latency_ms" in snap["histograms"]
    h = snap["histograms"]["llm.latency_ms"]
    assert h["count"] == 1
    assert h["min"] == 100.0
    assert h["max"] == 100.0
