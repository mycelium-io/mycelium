"""
Lightweight in-process metrics store for Mycelium backend.

Tracks embedding, LLM, indexing, memory, and synthesis operations with
counters, histograms, and cost-avoidance estimates. Exposed via
GET /api/metrics and consumed by `mycelium metrics show`.

Thread-safe (asyncio.to_thread calls) via a threading lock.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

_OPENAI_EMBEDDING_PRICE_PER_TOKEN = 0.02 / 1_000_000  # text-embedding-3-small
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


def record_embedding(source: str = "unknown", text_length: int = 0) -> None:
    """Record a single local embedding computation."""
    _inc("embeddings", "computed")
    _inc("embeddings", f"by_source.{source}")
    estimated_tokens = max(text_length // 4, _AVG_TOKENS_PER_EMBEDDING)
    _inc("embeddings", "estimated_tokens", estimated_tokens)
    _inc(
        "embeddings",
        "estimated_cost_avoided_usd",
        estimated_tokens * _OPENAI_EMBEDDING_PRICE_PER_TOKEN,
    )


def record_embedding_batch(source: str, count: int, total_text_length: int = 0) -> None:
    _inc("embeddings", "computed", count)
    _inc("embeddings", f"by_source.{source}", count)
    estimated_tokens = max(total_text_length // 4, _AVG_TOKENS_PER_EMBEDDING * count)
    _inc("embeddings", "estimated_tokens", estimated_tokens)
    _inc(
        "embeddings",
        "estimated_cost_avoided_usd",
        estimated_tokens * _OPENAI_EMBEDDING_PRICE_PER_TOKEN,
    )


def record_embedding_latency(duration_ms: float) -> None:
    _record_histogram("embeddings.latency_ms", duration_ms)


def record_llm_call(
    *,
    operation: str,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    duration_ms: float = 0.0,
    error: bool = False,
) -> None:
    """Record a backend LLM call (litellm completion)."""
    _inc("llm", "calls")
    _inc("llm", f"by_operation.{operation}")
    if model:
        _inc("llm", f"by_model.{model}")
    _inc("llm", "input_tokens", input_tokens)
    _inc("llm", "output_tokens", output_tokens)
    _inc("llm", "cost_usd", cost_usd)
    if error:
        _inc("llm", "errors")
    if duration_ms > 0:
        _record_histogram("llm.latency_ms", duration_ms)
        _record_histogram(f"llm.latency_ms.{operation}", duration_ms)


def record_index_run(
    *,
    target: str = "room",
    indexed: int = 0,
    skipped: int = 0,
    pruned: int = 0,
    errors: int = 0,
    duration_ms: float = 0.0,
) -> None:
    """Record a filesystem → pgvector indexing run."""
    _inc("indexer", "runs")
    _inc("indexer", "files_indexed", indexed)
    _inc("indexer", "files_skipped", skipped)
    _inc("indexer", "files_pruned", pruned)
    _inc("indexer", "errors", errors)
    _inc("indexer", f"by_target.{target}", indexed + skipped)
    if duration_ms > 0:
        _record_histogram("indexer.duration_ms", duration_ms)


def record_memory_write(scope: str = "namespace", embedded: bool = True) -> None:
    _inc("memory", "writes")
    _inc("memory", f"writes.{scope}")
    if embedded:
        _inc("memory", "writes_embedded")


def record_memory_search(duration_ms: float = 0.0) -> None:
    _inc("memory", "searches")
    if duration_ms > 0:
        _record_histogram("memory.search_latency_ms", duration_ms)


def record_synthesis(room: str = "", duration_ms: float = 0.0) -> None:
    _inc("synthesis", "runs")
    if duration_ms > 0:
        _record_histogram("synthesis.duration_ms", duration_ms)


def record_knowledge_ingestion(
    *,
    concepts: int = 0,
    relations: int = 0,
    duration_ms: float = 0.0,
    error: bool = False,
) -> None:
    _inc("knowledge", "ingestions")
    _inc("knowledge", "concepts_extracted", concepts)
    _inc("knowledge", "relations_extracted", relations)
    if error:
        _inc("knowledge", "errors")
    if duration_ms > 0:
        _record_histogram("knowledge.ingestion_duration_ms", duration_ms)


def snapshot() -> dict:
    """Return a JSON-serializable snapshot of all metrics."""
    with _lock:
        return {
            "started_at": _started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "counters": {k: dict(v) for k, v in _counters.items()},
            "histograms": {k: dict(v) for k, v in _histograms.items()},
        }
