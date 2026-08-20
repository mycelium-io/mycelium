# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Lightweight in-process metrics store for Mycelium backend.

Tracks embedding, LLM, indexing, and memory operations with
counters, histograms, and cost-avoidance estimates. Exposed via
GET /api/observability and consumed by `mycelium metrics show`.

Thread-safe via a threading lock; all public ``record_*`` functions
are guarded so they never raise — metrics failures are logged and
swallowed to avoid disrupting application codepaths.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger(__name__)

_PRICING_JSON = Path(
    os.environ.get(
        "MYCELIUM_PRICING_JSON",
        str(
            Path(__file__).resolve().parent.parent.parent.parent
            / "mycelium-cli"
            / "src"
            / "mycelium"
            / "data"
            / "pricing.json"
        ),
    )
)


def _load_embedding_price() -> float:
    """Load the embedding baseline price from pricing.json.

    Falls back to a hardcoded default if the file is missing or malformed.
    """
    try:
        data = json.loads(_PRICING_JSON.read_text())
        return data["embedding_baseline"]["input_per_token"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        _log.debug("Could not load pricing.json (%s), using default embedding price", exc)
        return 2e-08  # text-embedding-3-small fallback


_EMBEDDING_PRICE_PER_TOKEN = _load_embedding_price()
_AVG_TOKENS_PER_EMBEDDING = 60  # conservative estimate for short memory texts

_lock = threading.Lock()

_counters: dict[str, dict[str, int | float]] = {}
_histograms: dict[str, dict] = {}
_started_at: str = datetime.now(UTC).isoformat()


def _zero_histogram() -> dict:
    return {"count": 0, "sum": 0.0, "min": None, "max": None}


def _inc(namespace: str, key: str, delta: int | float = 1) -> None:
    with _lock:
        bucket = _counters.setdefault(namespace, {})
        bucket[key] = bucket.get(key, 0) + delta


def _record_histogram(name: str, value: float) -> None:
    with _lock:
        h = _histograms.setdefault(name, _zero_histogram())
        h["count"] += 1
        h["sum"] += value
        if h["min"] is None or value < h["min"]:
            h["min"] = value
        if h["max"] is None or value > h["max"]:
            h["max"] = value


# ── Public API ───────────────────────────────────────────────────────────


def _safe(fn):
    """Wrap a metrics function so it never raises.

    Logs at WARNING so silent data loss from bad inputs (e.g. non-int
    token counts from CFN ``_usage``) is visible in operational logs.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            _log.warning("metrics.%s failed", fn.__name__, exc_info=True)

    return wrapper


@_safe
def record_embedding(source: str = "unknown", text_length: int = 0) -> None:
    """Record a single local embedding computation."""
    _inc("embeddings", "computed")
    _inc("embeddings", f"by_source.{source}")
    estimated_tokens = max(text_length // 4, _AVG_TOKENS_PER_EMBEDDING)
    _inc("embeddings", "estimated_tokens", estimated_tokens)
    _inc(
        "embeddings",
        "estimated_cost_avoided_usd",
        estimated_tokens * _EMBEDDING_PRICE_PER_TOKEN,
    )


@_safe
def record_embedding_batch(source: str, count: int, total_text_length: int = 0) -> None:
    _inc("embeddings", "computed", count)
    _inc("embeddings", f"by_source.{source}", count)
    estimated_tokens = max(total_text_length // 4, _AVG_TOKENS_PER_EMBEDDING * count)
    _inc("embeddings", "estimated_tokens", estimated_tokens)
    _inc(
        "embeddings",
        "estimated_cost_avoided_usd",
        estimated_tokens * _EMBEDDING_PRICE_PER_TOKEN,
    )


@_safe
def record_embedding_latency(duration_ms: float) -> None:
    _record_histogram("embeddings.latency_ms", duration_ms)


@_safe
def record_llm_call(
    *,
    operation: str,
    model: str = "",
    room: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    duration_ms: float = 0.0,
    error: bool = False,
) -> None:
    """Record a backend LLM call (a Pi completion).

    Per-operation token totals are tracked alongside the grand totals so that
    callers (e.g. ``mycelium metrics show mycelium``) can show per-operation
    figures without having to assume that other operations (health probes,
    future heartbeats) contribute negligibly.

    Per-room counters are recorded when ``room`` is provided so the
    ``mycelium metrics show cost`` view can break down spend by the parent
    mycelium room. Sessions belonging to the same parent
    room (``mycelium_room:session:<uuid>``) are bucketed by the CLI
    renderer via the shared ``_parent_room`` helper, matching the rule
    used for ``cfn_llm.by_room.*``.
    """
    _inc("llm", "calls")
    _inc("llm", f"by_operation.{operation}")
    if model:
        _inc("llm", f"by_model.{model}")
    _inc("llm", "input_tokens", input_tokens)
    _inc("llm", "output_tokens", output_tokens)
    _inc("llm", f"by_operation.{operation}.input_tokens", input_tokens)
    _inc("llm", f"by_operation.{operation}.output_tokens", output_tokens)
    _inc("llm", "cost_usd", cost_usd)
    if room:
        _inc("llm", f"by_room.{room}.calls")
        _inc("llm", f"by_room.{room}.input_tokens", input_tokens)
        _inc("llm", f"by_room.{room}.output_tokens", output_tokens)
        _inc("llm", f"by_room.{room}.cost_usd", cost_usd)
    if error:
        _inc("llm", "errors")
        _inc("llm", f"by_operation.{operation}.errors")
        if room:
            _inc("llm", f"by_room.{room}.errors")
    if duration_ms > 0:
        _record_histogram("llm.latency_ms", duration_ms)
        _record_histogram(f"llm.latency_ms.{operation}", duration_ms)


@_safe
def record_index_run(
    *,
    target: str = "room",
    indexed: int = 0,
    skipped: int = 0,
    pruned: int = 0,
    errors: int = 0,
    duration_ms: float = 0.0,
) -> None:
    """Record a filesystem → JSONL indexing run."""
    _inc("indexer", "runs")
    _inc("indexer", "files_indexed", indexed)
    _inc("indexer", "files_skipped", skipped)
    _inc("indexer", "files_pruned", pruned)
    _inc("indexer", "errors", errors)
    _inc("indexer", f"by_target.{target}", indexed + skipped)
    if duration_ms > 0:
        _record_histogram("indexer.duration_ms", duration_ms)


@_safe
def record_memory_write(scope: str = "namespace", embedded: bool = True) -> None:
    _inc("memory", "writes")
    _inc("memory", f"writes.{scope}")
    if embedded:
        _inc("memory", "writes_embedded")


@_safe
def record_memory_search(
    duration_ms: float = 0.0,
    *,
    results_returned: int = 0,
) -> None:
    """Record a memory search operation.

    Args:
        duration_ms: Search latency
        results_returned: Number of results returned (data reuse indicator)
    """
    _inc("memory", "searches")
    if results_returned > 0:
        _inc("memory", "search_hits")
        _inc("memory", "results_returned", results_returned)
    else:
        _inc("memory", "search_misses")
    if duration_ms > 0:
        _record_histogram("memory.search_latency_ms", duration_ms)


def snapshot() -> dict:
    """Return a JSON-serializable snapshot of all metrics."""
    with _lock:
        return {
            "started_at": _started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "counters": {k: dict(v) for k, v in _counters.items()},
            "histograms": {k: dict(v) for k, v in _histograms.items()},
        }
