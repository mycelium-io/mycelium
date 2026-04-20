# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

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

from mycelium.commands.metrics import (
    _BACKGROUND_CHANNELS,
    _get_model_pricing,
    _oc_token_totals,
)

_PRICING_JSON = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "mycelium"
    / "data"
    / "pricing.json"
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
                    "matrix": {
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
                    "matrix": {"total": 1005, "cache_read": 800},
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
    pricing, label = _get_model_pricing(
        "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"
    )
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
