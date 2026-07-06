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


def test_cfn_llm_counter_sums_pipelines() -> None:
    counters = {
        "cfn_llm": {
            "by_pipeline.intent_discovery.calls": 2,
            "by_pipeline.generate_options.calls": 1,
            "by_pipeline.intent_discovery.input_tokens": 100,
            "by_pipeline.generate_options.output_tokens": 50,
            "calls": 999,
        }
    }
    assert cfn_llm_counter(counters, "calls") == 3
    assert cfn_llm_counter(counters, "input_tokens") == 100
    assert cfn_llm_token_total(counters) == 150


def test_cfn_llm_token_total_missing_returns_none() -> None:
    assert cfn_llm_token_total({}) is None
