# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Unit tests for the metrics display math.

These guard a class of bug that was present before the
feat/simple_metrics restructure: the cache hit-rate and savings
calculations were mathematically inconsistent with how LLM providers
actually bill cached prefixes, and the OpenClaw ``heartbeat`` channel
(idle-loop keep-alive traffic) was silently aggregated into headline
token totals, drowning real agent work.

What's covered:
  * _oc_token_totals correctly splits by-channel tokens into
    foreground (real work) and background (heartbeat) buckets, and
    can optionally fold background back in.
  * _oc_token_totals degrades gracefully when only aggregate
    ``counters.tokens.total`` exists (older metrics.json files).
  * pricing.json carries a cache_write_premium for every model
    entry — this field is load-bearing for any future net-savings
    calculation and easy to forget when new models are added.
  * _get_model_pricing returns the write premium alongside input
    price and read discount, and falls back sanely for unknown models.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mycelium.commands.metrics import (
    _BACKGROUND_CHANNELS,
    _build_pricing_entry,
    _discover_models_from_metrics,
    _estimate_cost,
    _get_model_pricing,
    _load_pricing,
    _oc_token_totals,
    _parse_add_spec,
    _resolve_litellm_key,
)

_PRICING_JSON = (
    Path(__file__).resolve().parent.parent / "src" / "mycelium" / "data" / "pricing.json"
)


# ── _oc_token_totals ─────────────────────────────────────────────────


def test_oc_token_totals_splits_heartbeat_from_foreground() -> None:
    """Background channels are removed from the default (foreground) bucket."""
    otel = {
        "counters": {
            "tokens": {
                "by_agent": {
                    "heartbeat": {
                        "input": 10,
                        "output": 20,
                        "cache_read": 1000,
                        "cache_write": 1000,
                        "total": 1030,
                    },
                    "discord": {
                        "input": 5,
                        "output": 200,
                        "cache_read": 800,
                        "cache_write": 100,
                        "total": 1005,
                    },
                }
            }
        }
    }

    fg, bg = _oc_token_totals(otel)

    assert fg["total"] == 1005
    assert fg["cache_read"] == 800
    assert fg["cache_write"] == 100
    assert bg["total"] == 1030
    assert bg["cache_read"] == 1000


def test_oc_token_totals_include_background_folds_back_in() -> None:
    """include_background=True produces the old combined total."""
    otel = {
        "counters": {
            "tokens": {
                "by_agent": {
                    "heartbeat": {"total": 1030, "cache_read": 1000},
                    "discord": {"total": 1005, "cache_read": 800},
                }
            }
        }
    }

    fg, bg = _oc_token_totals(otel, include_background=True)

    assert fg["total"] == 1030 + 1005
    assert fg["cache_read"] == 1000 + 800
    # Background bucket is zeroed so callers can't accidentally double-count.
    assert all(v == 0 for v in bg.values())


def test_oc_token_totals_falls_back_to_counters_total() -> None:
    """Older metrics.json files without by_agent still produce a total."""
    otel = {
        "counters": {
            "tokens": {
                "total": {
                    "input": 1,
                    "output": 2,
                    "cache_read": 3,
                    "cache_write": 4,
                    "total": 10,
                }
            }
        }
    }

    fg, bg = _oc_token_totals(otel)

    assert fg["total"] == 10
    assert fg["cache_read"] == 3
    assert all(v == 0 for v in bg.values())


def test_oc_token_totals_handles_empty_input() -> None:
    """No OTLP data at all → zeroed buckets, no crash."""
    fg, bg = _oc_token_totals(None)
    assert all(v == 0 for v in fg.values())
    assert all(v == 0 for v in bg.values())

    fg, bg = _oc_token_totals({})
    assert all(v == 0 for v in fg.values())
    assert all(v == 0 for v in bg.values())


def test_heartbeat_is_in_background_channels() -> None:
    """Sanity check: the specific channel name we filter on is still listed."""
    assert "heartbeat" in _BACKGROUND_CHANNELS


# ── pricing.json / _get_model_pricing ────────────────────────────────


def test_every_model_has_cache_write_premium() -> None:
    """Load-bearing field; easy to forget when adding a new model."""
    data = json.loads(_PRICING_JSON.read_text())
    for entry in data["models"]:
        assert "cache_write_premium" in entry, (
            f"model {entry.get('pattern')} is missing cache_write_premium"
        )
        assert entry["cache_write_premium"] >= 0, (
            f"cache_write_premium for {entry.get('pattern')} must be >= 0"
        )

    default = data["default"]
    assert "cache_write_premium" in default
    assert default["cache_write_premium"] >= 0


def test_get_model_pricing_returns_write_premium() -> None:
    """_get_model_pricing must expose write_premium for downstream math."""
    pricing, label = _get_model_pricing("bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert label == "claude-haiku-4"
    assert pricing["input"] == 1e-06
    assert pricing["cache_discount"] == 0.9
    # Anthropic 5-minute cache writes cost 1.25x input → premium = 0.25
    assert pricing["cache_write_premium"] == 0.25


def test_get_model_pricing_unknown_model_falls_back() -> None:
    """Unknown models get a conservative default, not a crash."""
    pricing, label = _get_model_pricing("some-brand-new-frontier-model")
    assert label == "unknown model"
    assert pricing["input"] > 0
    assert 0 <= pricing["cache_discount"] <= 1
    assert pricing["cache_write_premium"] >= 0


def test_openai_models_have_zero_write_premium() -> None:
    """OpenAI doesn't charge a separate cache-write premium."""
    pricing, label = _get_model_pricing("gpt-4o-mini")
    assert label == "gpt-4o-mini"
    assert pricing["cache_write_premium"] == 0.0


# ── pricing.json output_per_token ────────────────────────────────────


def test_every_model_has_output_per_token() -> None:
    """output_per_token is required for accurate cost estimates."""
    data = json.loads(_PRICING_JSON.read_text())
    for entry in data["models"]:
        assert "output_per_token" in entry, (
            f"model {entry.get('pattern')} is missing output_per_token"
        )
        assert entry["output_per_token"] > 0, (
            f"output_per_token for {entry.get('pattern')} must be > 0"
        )

    default = data["default"]
    assert "output_per_token" in default
    assert default["output_per_token"] > 0


def test_get_model_pricing_returns_output_rate() -> None:
    """_get_model_pricing must expose an output rate from pricing.json."""
    pricing, _ = _get_model_pricing("bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert "output" in pricing
    assert pricing["output"] > 0
    assert pricing["output"] > pricing["input"]


def test_get_model_pricing_unknown_model_output_from_default() -> None:
    """Unknown models must get default output rate, not a hardcoded 4x."""
    data = json.loads(_PRICING_JSON.read_text())
    expected_output = data["default"]["output_per_token"]
    pricing, _ = _get_model_pricing("some-brand-new-frontier-model")
    assert pricing["output"] == expected_output


# ── _estimate_cost ───────────────────────────────────────────────────


def test_estimate_cost_basic_input_output() -> None:
    """Smoke test: input + output tokens priced at model rates."""
    cost = _estimate_cost(
        input_tokens=1000,
        output_tokens=500,
        cache_read_tokens=0,
        cache_write_tokens=0,
        model="gpt-4o-mini",
    )
    pricing, _ = _get_model_pricing("gpt-4o-mini")
    expected = 1000 * pricing["input"] + 500 * pricing["output"]
    assert abs(cost - expected) < 1e-12


def test_estimate_cost_deducts_cached_from_input() -> None:
    """Cached tokens must NOT be double-billed at both full and discounted rate.

    provider semantics: prompt_tokens includes cached_tokens as a subset.
    So input_tokens=1000 with cache_read=400 means 600 at full rate + 400
    at the discounted cache-read rate.
    """
    pricing, _ = _get_model_pricing("gpt-4o-mini")
    input_rate = pricing["input"]
    cache_read_rate = input_rate * (1 - pricing["cache_discount"])

    cost = _estimate_cost(
        input_tokens=1000,
        output_tokens=0,
        cache_read_tokens=400,
        cache_write_tokens=0,
        model="gpt-4o-mini",
    )
    expected = 600 * input_rate + 400 * cache_read_rate
    assert abs(cost - expected) < 1e-12


def test_estimate_cost_cache_read_cannot_exceed_input() -> None:
    """If cache_read > input (shouldn't happen, but defensive), don't go negative."""
    cost = _estimate_cost(
        input_tokens=100,
        output_tokens=0,
        cache_read_tokens=200,
        cache_write_tokens=0,
        model="gpt-4o-mini",
    )
    assert cost >= 0


def test_estimate_cost_all_zero_is_free() -> None:
    assert _estimate_cost(0, 0, 0, 0, "gpt-4o-mini") == 0.0


# ── _build_pricing_entry ────────────────────────────────────────────


def test_build_pricing_entry_anthropic_with_cache() -> None:
    """Verify cache_discount and cache_write_premium computation from API data."""
    spec = {
        "pattern": "claude-sonnet-4",
        "provider": "anthropic",
        "litellm_key": "claude-sonnet-4-5",
    }
    api_data = {
        "input_cost_per_token": 3e-06,
        "output_cost_per_token": 1.5e-05,
        "cache_read_input_token_cost": 3e-07,
        "cache_creation_input_token_cost": 3.75e-06,
    }
    entry = _build_pricing_entry(spec, api_data)
    assert entry is not None
    assert entry["pattern"] == "claude-sonnet-4"
    assert entry["input_per_token"] == 3e-06
    assert entry["output_per_token"] == 1.5e-05
    assert entry["cache_discount"] == 0.9
    assert entry["cache_write_premium"] == 0.25


def test_build_pricing_entry_openai_no_cache_write() -> None:
    """OpenAI models typically have no cache write premium."""
    spec = {"pattern": "gpt-4o-mini", "provider": "openai", "litellm_key": "gpt-4o-mini"}
    api_data = {
        "input_cost_per_token": 1.5e-07,
        "output_cost_per_token": 6e-07,
        "cache_read_input_token_cost": 7.5e-08,
    }
    entry = _build_pricing_entry(spec, api_data)
    assert entry is not None
    assert entry["cache_write_premium"] == 0.0


def test_build_pricing_entry_missing_input_returns_none() -> None:
    """If the API returns no input pricing, entry should be skipped."""
    spec = {"pattern": "test-model", "provider": "openai", "litellm_key": "test"}
    entry = _build_pricing_entry(spec, {"output_cost_per_token": 1e-06})
    assert entry is None


def test_build_pricing_entry_missing_output_defaults_4x() -> None:
    """Models without output pricing fall back to 4x input."""
    spec = {"pattern": "test-model", "provider": "openai", "litellm_key": "test"}
    entry = _build_pricing_entry(spec, {"input_cost_per_token": 1e-06})
    assert entry is not None
    assert entry["output_per_token"] == 4e-06


def test_build_pricing_entry_no_cache_read_uses_default_discount() -> None:
    """Missing cache_read_input_token_cost -> default 90% discount."""
    spec = {"pattern": "test-model", "provider": "anthropic", "litellm_key": "test"}
    entry = _build_pricing_entry(
        spec, {"input_cost_per_token": 1e-06, "output_cost_per_token": 4e-06}
    )
    assert entry is not None
    assert entry["cache_discount"] == 0.9
    assert entry["cache_write_premium"] == 0.25


# ── _load_pricing (user cache vs bundled fallback) ──────────────────


def test_load_pricing_prefers_user_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When user pricing.json exists, it takes priority over bundled."""
    import mycelium.commands.metrics as mod

    user_pricing = tmp_path / "pricing.json"
    user_pricing.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-04T00:00:00+00:00",
                "source": "litellm_catalog_api",
                "models": [
                    {
                        "pattern": "test-model",
                        "input_per_token": 9.99e-06,
                        "output_per_token": 3e-05,
                        "cache_discount": 0.5,
                        "cache_write_premium": 0.1,
                        "litellm_key": "test",
                    }
                ],
                "default": {
                    "input_per_token": 1e-06,
                    "output_per_token": 4e-06,
                    "cache_discount": 0.9,
                    "cache_write_premium": 0.25,
                    "label": "unknown model",
                },
            }
        )
    )

    monkeypatch.setattr(mod, "_user_pricing_json", lambda: user_pricing)
    monkeypatch.setattr(mod, "_pricing_data", None)

    data = _load_pricing()
    assert data["source"] == "litellm_catalog_api"
    assert data["models"][0]["pattern"] == "test-model"

    monkeypatch.setattr(mod, "_pricing_data", None)


def test_load_pricing_falls_back_to_bundled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the user cache is missing, fall back to bundled pricing."""
    import mycelium.commands.metrics as mod

    nonexistent = tmp_path / "no-such-file.json"
    monkeypatch.setattr(mod, "_user_pricing_json", lambda: nonexistent)
    monkeypatch.setattr(mod, "_pricing_data", None)

    data = _load_pricing()
    assert data.get("models")
    assert data["models"][0]["pattern"] in ("claude-sonnet-4", "claude-3-7-sonnet")

    monkeypatch.setattr(mod, "_pricing_data", None)


def test_load_pricing_skips_corrupt_user_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corrupt user cache is skipped; bundled data loads instead."""
    import mycelium.commands.metrics as mod

    corrupt = tmp_path / "pricing.json"
    corrupt.write_text("{not valid json!!!")

    monkeypatch.setattr(mod, "_user_pricing_json", lambda: corrupt)
    monkeypatch.setattr(mod, "_pricing_data", None)

    data = _load_pricing()
    assert data.get("models")

    monkeypatch.setattr(mod, "_pricing_data", None)


def test_load_pricing_skips_empty_models_user_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User cache with empty models list is skipped."""
    import mycelium.commands.metrics as mod

    empty_models = tmp_path / "pricing.json"
    empty_models.write_text(json.dumps({"models": [], "default": {}}))

    monkeypatch.setattr(mod, "_user_pricing_json", lambda: empty_models)
    monkeypatch.setattr(mod, "_pricing_data", None)

    data = _load_pricing()
    assert len(data.get("models", [])) > 0

    monkeypatch.setattr(mod, "_pricing_data", None)


# ── _resolve_litellm_key ────────────────────────────────────────────


def test_resolve_litellm_key_strips_bedrock_global() -> None:
    result = _resolve_litellm_key("bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert result == "claude-haiku-4-5-20251001-v1:0"


def test_resolve_litellm_key_strips_bedrock() -> None:
    assert _resolve_litellm_key("bedrock/some-model") == "some-model"


def test_resolve_litellm_key_strips_anthropic_prefix() -> None:
    assert _resolve_litellm_key("anthropic/claude-3-opus") == "claude-3-opus"


def test_resolve_litellm_key_strips_openai_prefix() -> None:
    assert _resolve_litellm_key("openai/gpt-4o") == "gpt-4o"


def test_resolve_litellm_key_no_prefix_unchanged() -> None:
    assert _resolve_litellm_key("gpt-4o-mini") == "gpt-4o-mini"


def test_resolve_litellm_key_strips_only_first_matching_prefix() -> None:
    result = _resolve_litellm_key("bedrock/global.anthropic.claude-3-opus")
    assert result == "claude-3-opus"


# ── _discover_models_from_metrics ───────────────────────────────────


def test_discover_models_from_metrics_finds_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Models in metrics.json not covered by TRACKED_MODELS are returned."""
    import mycelium.commands.metrics as mod

    metrics = {
        "counters": {
            "tokens": {
                "by_model": {
                    "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0": {"total": 100},
                    "deepseek/deepseek-chat": {"total": 50},
                }
            }
        },
        "backend": {
            "counters": {
                "llm": {
                    "by_model.some-custom-model": 42,
                }
            }
        },
    }
    metrics_file = tmp_path / "metrics.json"
    metrics_file.write_text(json.dumps(metrics))
    monkeypatch.setattr(mod, "_metrics_json", lambda: metrics_file)

    result = _discover_models_from_metrics()

    assert "deepseek/deepseek-chat" in result
    assert "some-custom-model" in result
    assert not any("claude-haiku-4" in m for m in result)


def test_discover_models_from_metrics_empty_when_all_tracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns empty when all models in metrics are already tracked."""
    import mycelium.commands.metrics as mod

    metrics = {
        "counters": {
            "tokens": {
                "by_model": {
                    "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0": {"total": 100},
                }
            }
        },
        "backend": {"counters": {"llm": {}}},
    }
    metrics_file = tmp_path / "metrics.json"
    metrics_file.write_text(json.dumps(metrics))
    monkeypatch.setattr(mod, "_metrics_json", lambda: metrics_file)

    assert _discover_models_from_metrics() == []


def test_discover_models_from_metrics_handles_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns empty when metrics.json doesn't exist."""
    import mycelium.commands.metrics as mod

    monkeypatch.setattr(mod, "_metrics_json", lambda: tmp_path / "no-such-file.json")
    assert _discover_models_from_metrics() == []


# ── _parse_add_spec ─────────────────────────────────────────────────


def test_parse_add_spec_with_colon() -> None:
    result = _parse_add_spec("deepseek-v3:deepseek-chat")
    assert result["pattern"] == "deepseek-v3"
    assert result["litellm_key"] == "deepseek-chat"


def test_parse_add_spec_bare_key() -> None:
    result = _parse_add_spec("deepseek-chat")
    assert result["pattern"] == "deepseek-chat"
    assert result["litellm_key"] == "deepseek-chat"
