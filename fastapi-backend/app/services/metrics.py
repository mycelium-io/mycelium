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

# ── OTel meter bridge ─────────────────────────────────────────────────────────
# Lazy cache of OTel histogram instruments.  Populated on first use when the
# OTel SDK is active (TELEMETRY_ENABLED=true); returns a no-op stub otherwise.
# Kept here so every record_* function can write to OTel and the in-process
# store in one call without importing telemetry.py at module load time.
_otel_instruments: dict[str, object] = {}


def _otel_histogram(name: str, unit: str = "ms", description: str = ""):
    """Return (or create) an OTel histogram instrument for *name*.

    Returns None when the SDK is off so callers can guard cheaply.
    """
    if name in _otel_instruments:
        return _otel_instruments[name]
    try:
        from app.services.telemetry import get_meter

        meter = get_meter("mycelium.metrics")
        inst = meter.create_histogram(name, unit=unit, description=description)
        _otel_instruments[name] = inst
        return inst
    except Exception:
        _otel_instruments[name] = None  # cache the miss, don't retry
        return None


def _otel_record(
    name: str, value: float, unit: str = "ms", attrs: dict | None = None, description: str = ""
) -> None:
    """Write *value* to the OTel histogram *name* (no-op when SDK is off)."""
    inst = _otel_histogram(name, unit=unit, description=description)
    if inst is not None:
        try:
            inst.record(value, attributes=attrs or {})
        except Exception:
            pass


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

# Bounded sample lists for percentile computation (p95 for /health degradation
# thresholds and /api/observability).  Capped at 1000 values per histogram so
# memory is bounded regardless of uptime.
_SAMPLE_CAP = 1000
_samples: dict[str, list[float]] = {}


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
        # Bounded sample list for percentile computation.
        sl = _samples.setdefault(name, [])
        if len(sl) < _SAMPLE_CAP:
            sl.append(value)
        else:
            # Evict the oldest value in a ring-buffer style (simple and cheap).
            sl.pop(0)
            sl.append(value)


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
        _otel_record(
            "mycelium.llm.call.duration",
            duration_ms,
            attrs={
                "gen_ai.operation.name": operation or "",
                "gen_ai.request.model": model or "",
                "error": str(error).lower(),
            },
            description="LLM (Pi) call duration",
        )
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
        _otel_record(
            "mycelium.memory.search.duration",
            duration_ms,
            description="Memory semantic-search latency",
        )


# ── Non-LLM instrumentation ──────────────────────────────────────────────────


@_safe
def record_aligner_round(
    *,
    room: str = "",
    round_num: int = 0,
    duration_ms: float = 0.0,
    duration_excl_llm_ms: float = 0.0,
    outcome: str = "",
) -> None:
    """Record one NEGMAS SAO round inside a mediated negotiation.

    ``duration_ms`` is the total round wall-clock time (SLIM wait + Pi call +
    SAO logic). ``duration_excl_llm_ms`` is that total minus the Pi subprocess
    time accumulated in ``PiSession.total_pi_ms`` — it isolates the agent
    response latency and pure NEGMAS mechanism overhead from the LLM cost.
    Both histograms feed ``/api/observability`` and the OTel SDK when enabled.
    """
    _inc("aligner", "rounds")
    if room:
        _inc("aligner", f"by_room.{room}.rounds")
    if outcome:
        _inc("aligner", f"outcomes.{outcome}")
        if room:
            _inc("aligner", f"by_room.{room}.outcomes.{outcome}")
    if duration_ms > 0:
        _record_histogram("aligner.round_ms", duration_ms)
        _otel_record(
            "mycelium.aligner.round.duration",
            duration_ms,
            attrs={"mycelium.room": room or "", "mycelium.aligner.outcome": outcome or ""},
            description="Duration of one NEGMAS SAO round",
        )
    if duration_excl_llm_ms > 0:
        _record_histogram("aligner.round_excl_llm_ms", duration_excl_llm_ms)
        _otel_record(
            "mycelium.aligner.round.duration_excl_llm",
            duration_excl_llm_ms,
            attrs={"mycelium.room": room or ""},
            description="Aligner round duration excluding Pi LLM call time (SLIM wait + SAO logic)",
        )


@_safe
def record_aligner_run(
    *,
    room: str = "",
    rounds: int = 0,
    duration_ms: float = 0.0,
    outcome: str = "",
) -> None:
    """Record a complete aligner run (summon to commit/reject)."""
    _inc("aligner", "runs")
    if room:
        _inc("aligner", f"by_room.{room}.runs")
    if outcome:
        _inc("aligner", f"run_outcomes.{outcome}")
    if rounds > 0:
        _inc("aligner", "total_rounds", rounds)
    if duration_ms > 0:
        _record_histogram("aligner.run_ms", duration_ms)
        _otel_record(
            "mycelium.aligner.run.duration",
            duration_ms,
            attrs={
                "mycelium.room": room or "",
                "mycelium.aligner.outcome": outcome or "",
                "mycelium.aligner.rounds": str(rounds),
            },
            description="Total duration of one aligner negotiation run",
        )


@_safe
def record_slim_provision(
    *,
    room: str = "",
    duration_ms: float = 0.0,
    error: bool = False,
) -> None:
    """Record the latency of provisioning a SLIM channel for a room.

    Called after each successful or failed ``RoomChannelManager.provision``
    attempt. Surfaces ``slim.provision_ms`` in ``/api/observability`` (#486).
    """
    _inc("slim", "provisions")
    if error:
        _inc("slim", "provision_errors")
    if room:
        _inc("slim", f"by_room.{room}.provisions")
    if duration_ms > 0:
        _record_histogram("slim.provision_ms", duration_ms)
        _otel_record(
            "mycelium.slim.provision.duration",
            duration_ms,
            attrs={"mycelium.room": room or "", "error": str(error).lower()},
            description="SLIM channel provision latency",
        )


@_safe
def record_slim_receive_error(*, room: str = "") -> None:
    """Increment the SLIM receive-error counter for monitoring channel health."""
    _inc("slim", "receive_errors")
    if room:
        _inc("slim", f"by_room.{room}.receive_errors")


@_safe
def record_await_poll(
    *,
    room: str = "",
    handle: str = "",
    duration_ms: float = 0.0,
    delivered: bool = False,
) -> None:
    """Record an ``await`` long-poll duration (server-held participation).

    ``delivered`` is True when the poll returned a message (not a timeout).
    ``participate.await_delivered_ms`` tracks only delivered polls — this is
    the latency the health degradation threshold uses, since timed-out awaits
    are expected long-poll durations (up to 3600 s) that are not anomalies.
    ``participate.await_ms`` tracks all polls (delivered + timeout) for
    throughput accounting.
    """
    _inc("participate", "awaits")
    if delivered:
        _inc("participate", "delivered")
        if duration_ms > 0:
            _record_histogram("participate.await_delivered_ms", duration_ms)
            _otel_record(
                "mycelium.participate.await.duration",
                duration_ms,
                attrs={"mycelium.room": room or "", "mycelium.await.delivered": "true"},
                description="Delivered await long-poll latency",
            )
    else:
        _inc("participate", "timeouts")
    if room:
        _inc("participate", f"by_room.{room}.awaits")
    if duration_ms > 0:
        _record_histogram("participate.await_ms", duration_ms)


@_safe
def record_http_request(
    *,
    method: str = "",
    route: str = "",
    status_code: int = 0,
    duration_ms: float = 0.0,
) -> None:
    """Record an HTTP request to the backend (non-OTel fallback / augmentation).

    When the OTel SDK is active, ``FastAPIInstrumentor`` already captures these
    spans. This function lets the always-on in-process store track the same
    signals without requiring the SDK. Both write to the same histogram names.
    """
    _inc("http", "requests")
    if method:
        _inc("http", f"by_method.{method.upper()}")
    if route:
        _inc("http", f"by_route.{route}")
    if status_code:
        bucket = f"{status_code // 100}xx"
        _inc("http", f"by_status.{bucket}")
        if status_code >= 500:
            _inc("http", "errors")
    if duration_ms > 0:
        _record_histogram("http.request_ms", duration_ms)
        if route:
            _record_histogram(f"http.request_ms.{route}", duration_ms)


def snapshot() -> dict:
    """Return a JSON-serializable snapshot of all metrics."""
    with _lock:
        hists = {k: dict(v) for k, v in _histograms.items()}
        # Attach p95 to each histogram that has enough samples.
        pct = {}
        for name, sl in _samples.items():
            if len(sl) >= 5:
                sorted_sl = sorted(sl)
                idx = max(0, int(len(sorted_sl) * 0.95) - 1)
                pct[name] = sorted_sl[idx]
        return {
            "started_at": _started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "counters": {k: dict(v) for k, v in _counters.items()},
            "histograms": hists,
            "p95": pct,
        }


def p95(histogram_name: str) -> float | None:
    """Return the p95 latency for ``histogram_name``, or ``None`` if insufficient data."""
    with _lock:
        sl = _samples.get(histogram_name)
        if not sl or len(sl) < 5:
            return None
        sorted_sl = sorted(sl)
        idx = max(0, int(len(sorted_sl) * 0.95) - 1)
        return sorted_sl[idx]
