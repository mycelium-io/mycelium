"""Helpers for reading Mycelium backend /api/observability counters."""

from __future__ import annotations

from typing import Any


def observability_counters(obs: Any) -> dict:
    """Return the ``counters`` dict from an observability response."""
    if not isinstance(obs, dict):
        return {}
    counters = obs.get("counters")
    return counters if isinstance(counters, dict) else {}


def cfn_llm_counter(counters: dict, key: str) -> int:
    """Sum ``cfn_llm.by_pipeline.<pipeline>.<key>`` across all pipelines."""
    grp = counters.get("cfn_llm") or {}
    if not isinstance(grp, dict):
        return 0
    suffix = f".{key}"
    total = 0
    for k, v in grp.items():
        if k.startswith("by_pipeline.") and k.endswith(suffix):
            try:
                total += int(v)
            except (TypeError, ValueError):
                continue
    return total


def cfn_llm_token_total(counters: dict) -> int | None:
    """Return input+output token sum from cfn_llm counters, or None if absent."""
    inp = cfn_llm_counter(counters, "input_tokens")
    out = cfn_llm_counter(counters, "output_tokens")
    total = inp + out
    return total if total > 0 else None
