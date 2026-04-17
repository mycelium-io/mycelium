"""
Lightweight in-process metrics store for Mycelium backend.

Tracks embedding, LLM, indexing, memory, and synthesis operations with
counters, histograms, and cost-avoidance estimates. Exposed via
GET /api/metrics and consumed by `mycelium metrics show`.

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
    """Wrap a metrics function so it never raises."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            _log.debug("metrics.%s failed", fn.__name__, exc_info=True)

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
    """Record a filesystem → pgvector indexing run."""
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


@_safe
def record_synthesis(duration_ms: float = 0.0, *, error: bool = False) -> None:
    _inc("synthesis", "runs")
    if error:
        _inc("synthesis", "errors")
    if duration_ms > 0 and not error:
        _record_histogram("synthesis.duration_ms", duration_ms)


@_safe
def record_synthesis_reuse(*, had_cached: bool = False, memories_since: int = 0) -> None:
    """Record when a briefing reuses cached synthesis.

    Args:
        had_cached: Whether a cached synthesis was available
        memories_since: Number of memories added since last synthesis
    """
    _inc("synthesis", "briefings")
    if had_cached:
        _inc("synthesis", "cache_hits")
    else:
        _inc("synthesis", "cache_misses")
    if memories_since > 0:
        _record_histogram("synthesis.memories_since_last", float(memories_since))


@_safe
def record_knowledge_ingestion(
    *,
    concepts: int = 0,
    relations: int = 0,
    duration_ms: float = 0.0,
    error: bool = False,
    estimated_input_tokens: int = 0,
) -> None:
    _inc("knowledge", "ingestions")
    _inc("knowledge", "concepts_extracted", concepts)
    _inc("knowledge", "relations_extracted", relations)
    if error:
        _inc("knowledge", "errors")
    if duration_ms > 0:
        _record_histogram("knowledge.ingestion_duration_ms", duration_ms)
    if estimated_input_tokens > 0:
        _inc("knowledge", "estimated_input_tokens", estimated_input_tokens)
        _record_histogram("knowledge.estimated_input_tokens", float(estimated_input_tokens))


@_safe
def record_knowledge_query(
    *,
    query_type: str = "neighbour",
    nodes_queried: int = 0,
    results_returned: int = 0,
    duration_ms: float = 0.0,
    cache_hit: bool = False,
    error: bool = False,
) -> None:
    """Record a knowledge graph query operation.

    Args:
        query_type: Type of query (neighbour, path, concept, semantic)
        nodes_queried: Number of nodes in the query
        results_returned: Number of results (edges/paths) returned
        duration_ms: Query latency
        cache_hit: Whether results came from cache
        error: Whether the query failed (CFN transport/HTTP error)
    """
    _inc("knowledge", "queries")
    _inc("knowledge", f"queries.{query_type}")
    if error:
        _inc("knowledge", "query_errors")
    elif results_returned > 0:
        _inc("knowledge", "query_hits")
        _inc("knowledge", "results_returned", results_returned)
    else:
        _inc("knowledge", "query_misses")
    if cache_hit:
        _inc("knowledge", "cache_hits")
    if duration_ms > 0:
        _record_histogram("knowledge.query_latency_ms", duration_ms)


@_safe
def record_coordination_start(
    *,
    participants: int = 0,
) -> None:
    """Record the start of a coordination session."""
    _inc("coordination", "sessions_started")
    if participants > 0:
        _record_histogram("coordination.session_participants", float(participants))


@_safe
def record_coordination_round(
    *,
    room: str = "",
    round_num: int = 0,
    participants: int = 0,
    duration_ms: float = 0.0,
) -> None:
    """Record a single coordination/negotiation round."""
    _inc("coordination", "rounds")
    if room:
        _inc("coordination", f"by_room.{room}")
    if participants > 0:
        _record_histogram("coordination.participants", float(participants))
    if duration_ms > 0:
        _record_histogram("coordination.round_duration_ms", duration_ms)


@_safe
def record_consensus(
    *,
    room: str = "",
    total_rounds: int = 0,
    total_duration_ms: float = 0.0,
    participants: int = 0,
    outcome: str = "success",
) -> None:
    """Record completion of a coordination session (consensus or failure)."""
    _inc("coordination", "sessions_completed")
    _inc("coordination", f"outcome.{outcome}")
    if total_rounds > 0:
        _record_histogram("coordination.rounds_to_completion", float(total_rounds))
    if total_duration_ms > 0:
        _record_histogram("coordination.time_to_completion_ms", total_duration_ms)
    if outcome == "success" and total_rounds > 0:
        _inc("coordination", "consensus_reached")
        _record_histogram("coordination.rounds_to_consensus", float(total_rounds))
        if total_duration_ms > 0:
            _record_histogram("coordination.time_to_consensus_ms", total_duration_ms)


@_safe
def record_cfn_call(
    *,
    service: str,
    operation: str,
    duration_ms: float = 0.0,
    status_code: int = 0,
    error: bool = False,
) -> None:
    """Record an outbound HTTP call to a CFN service.

    Args:
        service: Target service — ``"node"`` or ``"mgmt"``.
        operation: Logical operation name, e.g. ``"shared_memories_query"``.
        duration_ms: Round-trip latency of the HTTP call.
        status_code: HTTP response status (0 if no response received).
        error: Whether the call failed (non-2xx, timeout, transport error).
    """
    _inc("cfn", "calls")
    _inc("cfn", f"calls.{service}")
    _inc("cfn", f"calls.{service}.{operation}")
    if error:
        _inc("cfn", "errors")
        _inc("cfn", f"errors.{service}")
    if status_code > 0:
        _inc("cfn", f"status.{status_code}")
    if duration_ms > 0:
        _record_histogram("cfn.latency_ms", duration_ms)
        _record_histogram(f"cfn.latency_ms.{service}", duration_ms)


def snapshot() -> dict:
    """Return a JSON-serializable snapshot of all metrics."""
    with _lock:
        return {
            "started_at": _started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "counters": {k: dict(v) for k, v in _counters.items()},
            "histograms": {k: dict(v) for k, v in _histograms.items()},
        }
