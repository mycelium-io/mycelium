"""Unit tests for observability counter helpers."""

from __future__ import annotations

from libs.observability_helpers import (
    cfn_llm_counter,
    cfn_llm_token_total,
    observability_counters,
)


def test_observability_counters_extracts_nested_dict() -> None:
    obs = {"counters": {"cfn_llm": {"by_pipeline.foo.calls": 3}}}
    assert observability_counters(obs) == {"cfn_llm": {"by_pipeline.foo.calls": 3}}


def test_cfn_llm_counter_prefers_top_level() -> None:
    # Top-level key wins over by_room.* sub-keys (current node-svc format).
    counters = {
        "cfn_llm": {
            "calls": 5,
            "input_tokens": 200,
            "output_tokens": 80,
            "by_room.e2e-room:session:abc.calls": 3,
            "by_room.e2e-room:session:abc.input_tokens": 100,
        }
    }
    assert cfn_llm_counter(counters, "calls") == 5
    assert cfn_llm_counter(counters, "input_tokens") == 200
    assert cfn_llm_token_total(counters) == 280


def test_cfn_llm_counter_falls_back_to_by_room() -> None:
    # When top-level key is absent, sum by_room.* sub-keys.
    counters = {
        "cfn_llm": {
            "by_room.room-a.input_tokens": 100,
            "by_room.room-b.input_tokens": 50,
        }
    }
    assert cfn_llm_counter(counters, "input_tokens") == 150


def test_cfn_llm_token_total_missing_returns_none() -> None:
    assert cfn_llm_token_total({}) is None
