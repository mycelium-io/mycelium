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
# Room identity registry: ``mas_id -> room_name``. Populated opportunistically
# by service code whenever the backend learns both at the same time (e.g.,
# coordination session start, knowledge ingest, CFN negotiation). Survives
# room deletion from the ``rooms`` table (which is destructive), so the
# ``mycelium metrics show`` per-room tables can keep displaying friendly
# names and mas_ids for transient rooms after they're gone. Reset on
# process restart (in-memory only, same lifecycle as counters/histograms).
_room_identities: dict[str, str] = {}
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
    """Record a backend LLM call (litellm completion).

    Per-operation token totals are tracked alongside the grand totals so that
    callers (e.g. ``mycelium metrics show mycelium``) can show per-operation
    figures without having to assume that other operations (health probes,
    future heartbeats) contribute negligibly. See issue #296.

    Per-room counters are recorded when ``room`` is provided so the
    ``mycelium metrics show cost`` view can break down spend by the parent
    mycelium room (see issue #297). Sessions belonging to the same parent
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


@_safe
def record_knowledge_ingestion(
    *,
    concepts: int = 0,
    relations: int = 0,
    duration_ms: float = 0.0,
    error: bool = False,
    estimated_input_tokens: int = 0,
    mas_id: str | None = None,
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
    if mas_id:
        _inc("knowledge", f"by_mas.{mas_id}.ingestions")
        if error:
            _inc("knowledge", f"by_mas.{mas_id}.errors")
        if estimated_input_tokens > 0:
            _inc("knowledge", f"by_mas.{mas_id}.estimated_input_tokens", estimated_input_tokens)


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
    if round_num > 0:
        _record_histogram("coordination.round_num", float(round_num))
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
    if room:
        _inc("coordination", f"completed_by_room.{room}")
        _inc("coordination", f"completed_by_room.{room}.{outcome}")
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
    _inc("cfn", f"status.{status_code}")
    if duration_ms > 0:
        _record_histogram("cfn.latency_ms", duration_ms)
        _record_histogram(f"cfn.latency_ms.{service}", duration_ms)


@_safe
def record_cfn_llm_usage(
    *,
    operation: str,
    room: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
    total_tokens: int = 0,
    llm_calls: int = 0,
    latency_ms: float = 0.0,
    by_operation: dict[str, dict] | None = None,
) -> None:
    """Record LLM token usage returned by CFN in ``meta.tokens`` response fields.

    Captures token counts from the cognition engines for both
    ``start_negotiation`` (round-1 options generation) and
    ``decide_negotiation`` responses. The decide path DOES make LLM calls on
    its terminal step — the semantic-alignment validation evaluator (retry
    decision) runs its own LLM call via ``get_llm_provider``, whose usage the
    CE folds into the same ``meta.tokens`` it returns; ordinary continuing
    rounds make no new LLM call (NegMAS advances deterministically over
    options already generated at round 1) and correctly report nothing.

    Parameter names (``prompt_tokens`` / ``completion_tokens``) match the CFN
    ``_usage`` snapshot produced by litellm, but metric keys are normalised to
    ``input_tokens`` / ``output_tokens`` for consistency with the ``llm``
    namespace.
    """
    _inc("cfn_llm", "calls", llm_calls)
    _inc("cfn_llm", "input_tokens", prompt_tokens)
    _inc("cfn_llm", "output_tokens", completion_tokens)
    _inc("cfn_llm", "cached_tokens", cached_tokens)
    _inc("cfn_llm", "total_tokens", total_tokens)
    if latency_ms > 0:
        _record_histogram("cfn_llm.latency_ms", latency_ms)
    if room:
        _inc("cfn_llm", f"by_room.{room}.calls", llm_calls)
        _inc("cfn_llm", f"by_room.{room}.input_tokens", prompt_tokens)
        _inc("cfn_llm", f"by_room.{room}.output_tokens", completion_tokens)
    if by_operation:
        for op_name, op_data in by_operation.items():
            op_calls = op_data.get("calls", 0)
            op_input = op_data.get("prompt_tokens", 0)
            op_output = op_data.get("completion_tokens", 0)
            _inc("cfn_llm", f"by_llm_operation.{op_name}.calls", op_calls)
            _inc("cfn_llm", f"by_llm_operation.{op_name}.input_tokens", op_input)
            _inc("cfn_llm", f"by_llm_operation.{op_name}.output_tokens", op_output)
            pipeline = op_name.split(".")[0] if "." in op_name else op_name
            _inc("cfn_llm", f"by_pipeline.{pipeline}.calls", op_calls)
            _inc("cfn_llm", f"by_pipeline.{pipeline}.input_tokens", op_input)
            _inc("cfn_llm", f"by_pipeline.{pipeline}.output_tokens", op_output)


@_safe
def record_room_identity(*, mas_id: str, room_name: str) -> None:
    """Capture a ``mas_id ↔ room_name`` mapping for the metric snapshot.

    The ``rooms`` table is hard-deleted (see ``models.Room`` — no
    ``deleted_at`` column), which means once a transient room is gone,
    neither ``mas_id → name`` nor ``name → mas_id`` can be resolved
    via ``/api/rooms`` anymore. The CLI's per-room tables then show
    ``(deleted)`` or blank MAS cells, making it impossible to
    cross-reference Knowledge Ingestion (keyed by mas_id) against CFN
    Coordination / CFN LLM Token Usage (keyed by room_name).

    Callers should invoke this whenever they have both values in scope
    (typically at session start or first activity for a room). It's
    a write-once cache — re-recording an existing pair is a no-op,
    and the recorder is permissive about empty inputs (silent skip)
    to keep service code call sites uncluttered.
    """
    if not mas_id or not room_name:
        return
    with _lock:
        # Only set once per mas_id: if a room is somehow renamed in flight,
        # the first observed name wins. Rooms are not renamable today, so
        # this is a defensive choice for forward-compat only.
        _room_identities.setdefault(str(mas_id), str(room_name))


@_safe
def resolve_room_for_mas(mas_id: str) -> str:
    """Look up the room name previously recorded for *mas_id*, or "" if unknown.

    Read-side counterpart to ``record_room_identity``, for call sites that
    have a mas_id but not the room name in scope (e.g. ``cfn_knowledge.py``'s
    query path, which is keyed by mas_id, not room). Returns "" rather than
    raising so callers can pass it straight through to a ``room=`` kwarg.
    """
    if not mas_id:
        return ""
    with _lock:
        return _room_identities.get(str(mas_id), "")


def snapshot() -> dict:
    """Return a JSON-serializable snapshot of all metrics."""
    with _lock:
        return {
            "started_at": _started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "counters": {k: dict(v) for k, v in _counters.items()},
            "histograms": {k: dict(v) for k, v in _histograms.items()},
            # Survives /api/rooms deletion — see ``record_room_identity``.
            "room_identities": dict(_room_identities),
        }
