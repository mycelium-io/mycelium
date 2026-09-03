# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Lightweight OTLP HTTP receiver for OpenClaw telemetry.

Accepts protobuf-encoded OTLP data on /v1/traces and /v1/metrics,
aggregates counters/histograms/sessions in memory, and persists to a JSON file.

Hub mode (default):  run as a Docker container via ``mycelium up --metrics``.
Spoke mode:          run via ``mycelium metrics collect``.  Stores OTLP data
                     locally *and* forwards the raw payloads to the hub
                     collector (agent-to-gateway pattern) so the hub can
                     build a unified cross-host view.
"""

from __future__ import annotations

import copy
import gzip
import json
import logging
import socket
import sqlite3
import threading
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

log = logging.getLogger(__name__)


def _ts_to_epoch_ms(ts: str) -> float:
    """Parse an ISO-8601 timestamp string to epoch milliseconds."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000


# Mode for shared data directories: rwxrwxr-x with setgid so files created
# inside inherit the directory's group. Lets the host user (who typically
# runs ``mycelium metrics ...``) and the in-container collector user share
# the volume without permission errors.
_SHARED_DIR_MODE = 0o2775
# Mode for shared regular files (e.g. traces.db): rw-rw-r--. Group write
# is the important bit; it lets the same group rotate between the host
# user and the in-container collector user without root-owned leftovers
# blocking writes.
_SHARED_FILE_MODE = 0o664


def _ensure_shared_dir(path: Path) -> None:
    """Create *path* (and parents) and make it group-writable + setgid.

    Also normalizes permissions on any regular files already inside *path*
    to ``0o664``. This unblocks legacy installs where a previous root-mode
    collector created files (notably ``traces.db``) that the current
    non-root collector user can't write.

    Safe to call repeatedly; chmod is best-effort and silently ignored if
    we don't own the entry (e.g. created by another user).
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(_SHARED_DIR_MODE)
    except PermissionError:
        pass
    try:
        for child in path.iterdir():
            if not child.is_file() or child.is_symlink():
                continue
            try:
                child.chmod(_SHARED_FILE_MODE)
            except PermissionError:
                pass
    except OSError:
        pass


_MAX_SESSIONS = 200
_MAX_TRACES = 500
_MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MiB guard against oversized payloads


_SPAN_KIND_MAP = {
    0: "unspecified",
    1: "internal",
    2: "server",
    3: "client",
    4: "producer",
    5: "consumer",
}
_STATUS_MAP = {0: "unset", 1: "ok", 2: "error"}

_TRACES_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id     TEXT NOT NULL,
    span_id      TEXT NOT NULL PRIMARY KEY,
    parent_span_id TEXT NOT NULL DEFAULT '',
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'internal',
    service      TEXT NOT NULL DEFAULT '',
    host         TEXT NOT NULL DEFAULT '',
    start_time   TEXT NOT NULL,
    duration_ms  REAL NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'unset',
    status_message TEXT NOT NULL DEFAULT '',
    attributes   TEXT NOT NULL DEFAULT '{}',
    -- JSON list of OTel span events (timestamped log-like records the
    -- gateway / instrumentation attached mid-span: exceptions, prompt
    -- build steps, tool I/O snapshots, etc.). Each entry is
    -- {"time": iso8601, "name": str, "attributes": {...}}.
    events       TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_created_at ON spans(created_at);
CREATE INDEX IF NOT EXISTS idx_spans_start_time ON spans(start_time);
CREATE INDEX IF NOT EXISTS idx_spans_host ON spans(host);
"""

_DEFAULT_RETENTION_DAYS = 7


class TraceStore:
    """SQLite-backed trace span storage with automatic retention cleanup."""

    def __init__(self, db_path: Path, retention_days: int = _DEFAULT_RETENTION_DAYS) -> None:
        self._db_path = db_path
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._last_cleanup = 0.0

        _ensure_shared_dir(db_path.parent)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate_columns(conn)
        conn.executescript(_TRACES_SCHEMA)
        conn.close()
        log.info("Trace store opened: %s (retention=%dd)", db_path, retention_days)

    @staticmethod
    def _migrate_columns(conn: sqlite3.Connection) -> None:
        """Apply additive column migrations to an existing spans table."""
        cursor = conn.execute("PRAGMA table_info(spans)")
        columns = {row[1] for row in cursor.fetchall()}
        if not columns:
            return  # fresh DB, table doesn't exist yet; schema script will create it
        if "host" not in columns:
            conn.execute("ALTER TABLE spans ADD COLUMN host TEXT NOT NULL DEFAULT ''")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_host ON spans(host)")
            conn.commit()
            log.info("Migrated spans table: added 'host' column")
        if "events" not in columns:
            # Existing rows get '[]' so downstream code never has to handle NULL.
            conn.execute("ALTER TABLE spans ADD COLUMN events TEXT NOT NULL DEFAULT '[]'")
            conn.commit()
            log.info("Migrated spans table: added 'events' column")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path), timeout=10)

    def ingest_traces(
        self,
        request_bytes: bytes,
        *,
        is_json: bool = False,
        source_ip: str = "",
    ) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        msg = ExportTraceServiceRequest()
        if is_json:
            from google.protobuf.json_format import Parse

            Parse(request_bytes, msg)
        else:
            msg.ParseFromString(request_bytes)

        rows: list[tuple] = []
        for rs in msg.resource_spans:
            resource_attrs = _attrs_dict(rs.resource.attributes) if rs.resource else {}
            service_name = str(resource_attrs.get("service.name", ""))
            host = (
                str(resource_attrs.get("host.name", ""))
                or str(resource_attrs.get("service.instance.id", ""))
                or source_ip
            )
            for ss in rs.scope_spans:
                for span in ss.spans:
                    rows.append(self._span_to_row(span, service_name, host))

        if not rows:
            return

        with self._lock:
            conn = self._connect()
            try:
                conn.executemany(
                    "INSERT OR REPLACE INTO spans "
                    "(trace_id, span_id, parent_span_id, name, kind, service, host, "
                    " start_time, duration_ms, status, status_message, attributes, events) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                conn.commit()
            finally:
                conn.close()

    def _span_to_row(self, span, service_name: str, host: str = "") -> tuple:
        trace_id = span.trace_id.hex() if isinstance(span.trace_id, bytes) else str(span.trace_id)
        span_id = span.span_id.hex() if isinstance(span.span_id, bytes) else str(span.span_id)
        parent_id = (
            span.parent_span_id.hex()
            if isinstance(span.parent_span_id, bytes) and span.parent_span_id
            else ""
        )
        start_ns = span.start_time_unix_nano
        end_ns = span.end_time_unix_nano
        duration_ms = (end_ns - start_ns) / 1_000_000 if end_ns > start_ns else 0
        start_iso = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=UTC).isoformat()
        attrs = _attrs_dict(span.attributes)
        kind = _SPAN_KIND_MAP.get(span.kind, "unknown")
        status_code = span.status.code if span.status else 0
        status_msg = span.status.message if span.status else ""

        # Capture OTel span events; these are the closest thing the
        # protocol has to "log lines attached to a span" and are what
        # gives users a chance to see *what happened* mid-span. We
        # deliberately keep the same shape exporters use over the wire so
        # the JSON is self-describing for ad-hoc SQL.
        events: list[dict] = []
        for ev in getattr(span, "events", []) or []:
            ev_ns = getattr(ev, "time_unix_nano", 0) or 0
            try:
                ev_iso = (
                    datetime.fromtimestamp(ev_ns / 1_000_000_000, tz=UTC).isoformat()
                    if ev_ns
                    else ""
                )
            except (OverflowError, OSError, ValueError):
                ev_iso = ""
            events.append(
                {
                    "time": ev_iso,
                    "name": ev.name,
                    "attributes": _attrs_dict(ev.attributes),
                }
            )

        return (
            trace_id,
            span_id,
            parent_id,
            span.name,
            kind,
            service_name,
            host,
            start_iso,
            round(duration_ms, 2),
            _STATUS_MAP.get(status_code, "unknown"),
            status_msg,
            json.dumps(attrs, default=str),
            json.dumps(events, default=str),
        )

    def get_recent_traces(self, limit: int = 100, *, host: str | None = None) -> list[dict]:
        """Return recent traces as a list of trace summary objects, newest first.

        Each trace includes its full list of spans for waterfall rendering.
        When *host* is given, only traces that contain at least one span from
        that host are returned.

        No lock required: SQLite WAL mode supports concurrent readers.
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            if host:
                trace_ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT DISTINCT trace_id FROM spans WHERE host = ? "
                        "ORDER BY start_time DESC LIMIT ?",
                        (host, limit * 20),
                    ).fetchall()
                ]
            else:
                trace_ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT DISTINCT trace_id FROM spans ORDER BY start_time DESC LIMIT ?",
                        (limit * 20,),
                    ).fetchall()
                ]
            seen: list[str] = []
            seen_set: set[str] = set()
            for tid in trace_ids:
                if tid not in seen_set:
                    seen.append(tid)
                    seen_set.add(tid)
                if len(seen) >= limit:
                    break

            if not seen:
                return []

            placeholders = ",".join("?" * len(seen))
            all_rows = conn.execute(
                f"SELECT * FROM spans WHERE trace_id IN ({placeholders}) "
                "ORDER BY trace_id, start_time",
                seen,
            ).fetchall()

            spans_by_trace: dict[str, list[dict]] = {}
            for r in all_rows:
                span_host = r["host"] or ""
                # sqlite3.Row supports column lookup via `.keys()`; `in row`
                # would test against values, so we genuinely need `.keys()`.
                events_raw = r["events"] if "events" in r.keys() else "[]"  # noqa: SIM118
                span = {
                    "trace_id": r["trace_id"],
                    "span_id": r["span_id"],
                    "parent_span_id": r["parent_span_id"],
                    "name": r["name"],
                    "kind": r["kind"],
                    "service": r["service"],
                    "host": span_host,
                    "start_time": r["start_time"],
                    "duration_ms": r["duration_ms"],
                    "status": r["status"],
                    "status_message": r["status_message"],
                    "attributes": json.loads(r["attributes"]),
                    "events": json.loads(events_raw or "[]"),
                }
                spans_by_trace.setdefault(r["trace_id"], []).append(span)

            result: list[dict] = []
            for trace_id in seen:
                spans = spans_by_trace.get(trace_id, [])
                if not spans:
                    continue

                root_spans = [s for s in spans if not s["parent_span_id"]]
                root = root_spans[0] if root_spans else spans[0]

                starts = [_ts_to_epoch_ms(s["start_time"]) for s in spans]
                ends = [st + s["duration_ms"] for st, s in zip(starts, spans, strict=True)]
                total_duration = max(ends) - min(starts) if starts else 0

                has_error = any(s["status"] == "error" for s in spans)

                agent = ""
                for s in spans:
                    a = s.get("attributes", {})
                    agent = (
                        str(a.get("openclaw.channel", ""))
                        or str(a.get("openclaw.agent", ""))
                        or str(a.get("gen_ai.agent", ""))
                    )
                    if agent:
                        break

                hosts_in_trace = sorted({s["host"] for s in spans if s["host"]})

                result.append(
                    {
                        "trace_id": trace_id,
                        "root_span": root["name"],
                        "service": root.get("service", ""),
                        "agent": agent,
                        "host": root.get("host", ""),
                        "hosts": hosts_in_trace,
                        "start_time": root["start_time"],
                        "duration_ms": round(total_duration, 2),
                        "span_count": len(spans),
                        "has_error": has_error,
                        "spans": spans,
                    }
                )
            return result
        finally:
            conn.close()

    def get_hosts(self) -> list[dict]:
        """Return distinct hosts with span counts and last-seen times.

        No lock required: SQLite WAL mode supports concurrent readers.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT host, COUNT(*) AS span_count, MAX(start_time) AS last_seen, "
                "COUNT(DISTINCT trace_id) AS trace_count, "
                "SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count "
                "FROM spans WHERE host != '' GROUP BY host ORDER BY last_seen DESC"
            ).fetchall()

            agents_rows = conn.execute(
                "SELECT host, json_extract(attributes, '$.\"openclaw.channel\"') AS agent "
                "FROM spans "
                "WHERE host != '' "
                "AND json_extract(attributes, '$.\"openclaw.channel\"') IS NOT NULL "
                "AND json_extract(attributes, '$.\"openclaw.channel\"') != '' "
                "GROUP BY host, agent"
            ).fetchall()

            agents_by_host: dict[str, list[str]] = {}
            for row in agents_rows:
                agents_by_host.setdefault(row[0], []).append(row[1])

            result = []
            for r in rows:
                host_val, span_count, last_seen, trace_count, error_count = r
                result.append(
                    {
                        "host": host_val,
                        "span_count": span_count,
                        "trace_count": trace_count,
                        "last_seen": last_seen,
                        "agents": sorted(agents_by_host.get(host_val, [])),
                        "error_count": error_count,
                    }
                )
            return result
        finally:
            conn.close()

    def cleanup_old_spans(self) -> int:
        """Delete spans older than the retention period. Returns count deleted."""
        import time

        now = time.monotonic()
        if now - self._last_cleanup < 3600:
            return 0
        self._last_cleanup = now

        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "DELETE FROM spans WHERE created_at < datetime('now', ?)",
                    (f"-{self._retention_days} days",),
                )
                deleted = cursor.rowcount
                if deleted > 0:
                    conn.execute("PRAGMA incremental_vacuum")
                conn.commit()
                if deleted > 0:
                    log.info(
                        "Trace cleanup: deleted %d spans older than %d days",
                        deleted,
                        self._retention_days,
                    )
                return deleted
            finally:
                conn.close()


class MetricsStore:
    """In-memory aggregation of OTLP counters, histograms, and session records."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        # Per-host raw counter buckets. Each host pushes its own cumulative
        # values via OTLP (overwriting per host is correct), but the
        # cross-host rollup exposed as ``counters`` in ``to_dict()`` MUST be
        # a sum across hosts (otherwise the host that pushed last clobbers
        # everyone else's contribution). See ``_aggregate_counters_locked``.
        self._counters_by_host: dict[str, dict] = {}
        # Histograms are emitted by individual hosts as deltas on a
        # cumulative count/sum; we just keep the latest per-host snapshot
        # and merge at read time. Same overwriting concern applies.
        self._histograms_by_host: dict[str, dict] = {}
        self._sessions: dict[str, dict] = {}
        self._backend_metrics: dict | None = None
        self._by_host: dict[str, dict] = {}
        # Per-target Prometheus scrape state, keyed by config-supplied name.
        # Populated by `_fetch_scrape_targets` in the collector poller thread.
        self._scrape_targets: dict[str, dict] = {}

    @staticmethod
    def _empty_counter_bucket() -> dict:
        """Empty counter bucket matching the public ``counters`` snapshot shape."""
        return {
            "tokens": {"by_agent": {}, "by_model": {}, "total": _zero_tokens()},
            "cost_usd": {"by_agent": {}, "by_model": {}, "total": 0.0},
            "messages": {"processed": 0, "queued": 0},
            "webhooks": {"received": 0, "errors": 0},
            "lanes": {"enqueue": 0, "dequeue": 0},
            "sessions_state": {},
            "sessions_stuck": 0,
            "run_attempts": 0,
        }

    @staticmethod
    def _empty_histogram_bucket() -> dict:
        """Empty histogram bucket matching the public ``histograms`` snapshot shape."""
        return {
            "run_duration_ms": _zero_histogram(),
            "message_duration_ms": _zero_histogram(),
            "queue_depth": _zero_histogram(),
            "queue_wait_ms": _zero_histogram(),
            "context_tokens": _zero_histogram(),
            "webhook_duration_ms": _zero_histogram(),
            "session_stuck_age_ms": _zero_histogram(),
            "by_agent": {},
        }

    def _ensure_counter_bucket(self, host: str) -> dict:
        """Return (and lazily create) the per-host counter bucket.

        ``host`` may be empty when the OTLP push has no usable
        ``host.name``/``service.instance.id`` resource attribute and no
        source IP. We bucket those under ``"unknown"`` so they still get
        counted (rather than overwriting each other in a shared global).
        """
        key = host or "unknown"
        if key not in self._counters_by_host:
            self._counters_by_host[key] = self._empty_counter_bucket()
        return self._counters_by_host[key]

    def _ensure_histogram_bucket(self, host: str) -> dict:
        """Return (and lazily create) the per-host histogram bucket."""
        key = host or "unknown"
        if key not in self._histograms_by_host:
            self._histograms_by_host[key] = self._empty_histogram_bucket()
        return self._histograms_by_host[key]

    @staticmethod
    def _merge_token_dict(dst: dict, src: dict) -> None:
        """Sum ``src`` token counts into ``dst`` (input/output/cache_*/total)."""
        for k, v in src.items():
            dst[k] = dst.get(k, 0) + v

    def _aggregate_counters_locked(self) -> dict:
        """Sum the per-host counter buckets into a single rolled-up view.

        Cumulative counters are reported as a running total per host, so
        the correct cross-host value is the SUM of each host's latest
        reported value.
        """
        if not self._counters_by_host:
            return self._empty_counter_bucket()

        agg = self._empty_counter_bucket()
        for bucket in self._counters_by_host.values():
            # tokens.total / tokens.by_agent / tokens.by_model
            self._merge_token_dict(agg["tokens"]["total"], bucket["tokens"]["total"])
            for agent, tk in bucket["tokens"]["by_agent"].items():
                target = agg["tokens"]["by_agent"].setdefault(agent, _zero_tokens())
                self._merge_token_dict(target, tk)
            for model, tk in bucket["tokens"]["by_model"].items():
                target = agg["tokens"]["by_model"].setdefault(model, _zero_tokens())
                self._merge_token_dict(target, tk)

            # cost_usd.total / by_agent / by_model
            agg["cost_usd"]["total"] += bucket["cost_usd"]["total"]
            for agent, v in bucket["cost_usd"]["by_agent"].items():
                agg["cost_usd"]["by_agent"][agent] = agg["cost_usd"]["by_agent"].get(agent, 0.0) + v
            for model, v in bucket["cost_usd"]["by_model"].items():
                agg["cost_usd"]["by_model"][model] = agg["cost_usd"]["by_model"].get(model, 0.0) + v

            # Simple integer/float gauges that should sum across hosts
            for key in ("processed", "queued"):
                agg["messages"][key] += bucket["messages"].get(key, 0)
            for key in ("received", "errors"):
                agg["webhooks"][key] += bucket["webhooks"].get(key, 0)
            for key in ("enqueue", "dequeue"):
                agg["lanes"][key] += bucket["lanes"].get(key, 0)
            for state, v in bucket["sessions_state"].items():
                agg["sessions_state"][state] = agg["sessions_state"].get(state, 0) + v
            agg["sessions_stuck"] += bucket.get("sessions_stuck", 0)
            agg["run_attempts"] += bucket.get("run_attempts", 0)

        return agg

    def _aggregate_histograms_locked(self) -> dict:
        """Merge per-host histogram snapshots into a single rolled-up view.

        Each (count, sum, min, max) is reported per-host; the cross-host
        merge sums counts/sums and takes the min/max of mins/maxes.
        """
        if not self._histograms_by_host:
            return self._empty_histogram_bucket()

        agg = self._empty_histogram_bucket()
        flat_keys = [
            "run_duration_ms",
            "message_duration_ms",
            "queue_depth",
            "queue_wait_ms",
            "context_tokens",
            "webhook_duration_ms",
            "session_stuck_age_ms",
        ]
        for bucket in self._histograms_by_host.values():
            for key in flat_keys:
                _merge_histogram(agg[key], bucket.get(key) or {})
            for agent, agent_h in bucket.get("by_agent", {}).items():
                target = agg["by_agent"].setdefault(agent, {})
                for key, val in agent_h.items():
                    target.setdefault(key, _zero_histogram())
                    _merge_histogram(target[key], val)
        return agg

    def set_backend_metrics(self, data: dict | None) -> None:
        with self.lock:
            self._backend_metrics = data

    def set_scrape_target(self, name: str, data: dict | None) -> None:
        """Record the latest scrape result for a Prometheus target by name.

        ``data`` is the rolled-up dict from
        ``prom_scrape.aggregate_http_red(...)``; see that helper for shape.
        Passing None records that the target was unreachable on the last
        attempt; this is preserved (rather than dropped) so the panel can
        surface "target degraded" rather than silently disappear.
        """
        with self.lock:
            self._scrape_targets[name] = {
                "data": data,
                "scraped_at": datetime.now(UTC).isoformat(),
            }

    def to_dict(self) -> dict:
        with self.lock:
            sessions = sorted(
                self._sessions.values(),
                key=lambda s: s.get("timestamp", ""),
                reverse=True,
            )[:_MAX_SESSIONS]
            result = {
                "updated_at": datetime.now(UTC).isoformat(),
                "counters": self._aggregate_counters_locked(),
                "histograms": self._aggregate_histograms_locked(),
                "sessions": copy.deepcopy(sessions),
            }
            if self._backend_metrics:
                result["backend"] = copy.deepcopy(self._backend_metrics)
            if self._scrape_targets:
                result["scrape"] = copy.deepcopy(self._scrape_targets)
            if self._by_host:
                result["by_host"] = copy.deepcopy(self._by_host)
            # Per-host counter/histogram buckets, persisted so that a
            # collector restart can reload them without losing the
            # cross-host disambiguation. Aggregating them back into a
            # single ``counters`` view on reload would double-count once
            # any host pushes its next cumulative sample.
            if self._counters_by_host:
                result["counters_by_host"] = copy.deepcopy(self._counters_by_host)
            if self._histograms_by_host:
                result["histograms_by_host"] = copy.deepcopy(self._histograms_by_host)
            return result

    def ingest_metrics(
        self, request_bytes: bytes, *, is_json: bool = False, source_ip: str = ""
    ) -> None:
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
            ExportMetricsServiceRequest,
        )

        msg = ExportMetricsServiceRequest()
        if is_json:
            from google.protobuf.json_format import Parse

            Parse(request_bytes, msg)
        else:
            msg.ParseFromString(request_bytes)

        with self.lock:
            for rm in msg.resource_metrics:
                resource_attrs = _attrs_dict(rm.resource.attributes) if rm.resource else {}
                host = (
                    str(resource_attrs.get("host.name", ""))
                    or str(resource_attrs.get("service.instance.id", ""))
                    or source_ip
                )
                for sm in rm.scope_metrics:
                    for metric in sm.metrics:
                        self._process_metric(metric, host)
                        if host:
                            self._track_host_metric(host, metric)

    def ingest_traces(
        self, request_bytes: bytes, *, is_json: bool = False, source_ip: str = ""
    ) -> None:
        """Process model.usage spans for session aggregation.

        The raw request_bytes are also forwarded to a TraceStore (if set)
        for full trace capture; see ``trace_store`` attribute.
        """
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        msg = ExportTraceServiceRequest()
        if is_json:
            from google.protobuf.json_format import Parse

            Parse(request_bytes, msg)
        else:
            msg.ParseFromString(request_bytes)

        with self.lock:
            for rs in msg.resource_spans:
                resource_attrs = _attrs_dict(rs.resource.attributes) if rs.resource else {}
                host = (
                    str(resource_attrs.get("host.name", ""))
                    or str(resource_attrs.get("service.instance.id", ""))
                    or source_ip
                )
                for ss in rs.scope_spans:
                    for span in ss.spans:
                        self._process_span(span)
                        if host:
                            self._track_host_span(host, span)

    def _process_metric(self, metric, host: str = "") -> None:  # noqa: C901
        """Record a single OTLP metric.

        The ``host`` arg is mandatory for correct cross-host rollups:
        each host reports its own running cumulative counter, so they
        must be kept in separate buckets and summed at read time. See
        ``_aggregate_counters_locked``. If ``host`` is empty (no
        resource attribute and no source IP), the data is bucketed
        under ``"unknown"`` rather than silently overwriting other
        hosts' values.
        """
        name = metric.name
        counters = self._ensure_counter_bucket(host)
        histograms = self._ensure_histogram_bucket(host)

        if metric.HasField("sum"):
            for dp in metric.sum.data_points:
                attrs = _attrs_dict(dp.attributes)
                value = dp.as_double if dp.HasField("as_double") else float(dp.as_int)

                if name == "openclaw.tokens":
                    token_type = attrs.get("openclaw.token", "total")
                    agent = attrs.get("openclaw.channel", "")
                    model = attrs.get("openclaw.model", "")

                    if token_type in counters["tokens"]["total"]:
                        counters["tokens"]["total"][token_type] = value

                    if agent:
                        bucket = counters["tokens"]["by_agent"].setdefault(agent, _zero_tokens())
                        if token_type in bucket:
                            bucket[token_type] = value

                    if model:
                        bucket = counters["tokens"]["by_model"].setdefault(model, _zero_tokens())
                        if token_type in bucket:
                            bucket[token_type] = value

                elif name == "openclaw.cost.usd":
                    agent = attrs.get("openclaw.channel", "")
                    model = attrs.get("openclaw.model", "")
                    counters["cost_usd"]["total"] = value
                    if agent:
                        counters["cost_usd"]["by_agent"][agent] = value
                    if model:
                        counters["cost_usd"]["by_model"][model] = value

                elif name == "openclaw.message.processed":
                    counters["messages"]["processed"] = value

                elif name == "openclaw.message.queued":
                    counters["messages"]["queued"] = value

                elif name == "openclaw.webhook.received":
                    counters["webhooks"]["received"] = value

                elif name == "openclaw.webhook.error":
                    counters["webhooks"]["errors"] = value

                elif name == "openclaw.queue.lane.enqueue":
                    counters["lanes"]["enqueue"] = value

                elif name == "openclaw.queue.lane.dequeue":
                    counters["lanes"]["dequeue"] = value

                elif name == "openclaw.session.state":
                    state = attrs.get("openclaw.state", "unknown")
                    counters["sessions_state"][state] = value

                elif name == "openclaw.session.stuck":
                    counters["sessions_stuck"] = value

                elif name == "openclaw.run.attempt":
                    counters["run_attempts"] = value

        elif metric.HasField("histogram"):
            for dp in metric.histogram.data_points:
                attrs = _attrs_dict(dp.attributes)
                h_count = dp.count
                h_sum = dp.sum
                h_min = dp.min if dp.HasField("min") else None
                h_max = dp.max if dp.HasField("max") else None
                update = {"count": h_count, "sum": h_sum, "min": h_min, "max": h_max}

                key = None
                if name == "openclaw.run.duration_ms":
                    key = "run_duration_ms"
                elif name == "openclaw.message.duration_ms":
                    key = "message_duration_ms"
                elif name == "openclaw.queue.depth":
                    key = "queue_depth"
                elif name == "openclaw.queue.wait_ms":
                    key = "queue_wait_ms"
                elif name == "openclaw.context.tokens":
                    key = "context_tokens"
                elif name == "openclaw.webhook.duration_ms":
                    key = "webhook_duration_ms"
                elif name == "openclaw.session.stuck_age_ms":
                    key = "session_stuck_age_ms"

                if key:
                    histograms[key] = update
                    agent = attrs.get("openclaw.channel", "")
                    if agent:
                        agent_h = histograms["by_agent"].setdefault(agent, {})
                        agent_h[key] = update

    def _process_span(self, span) -> None:
        if span.name != "openclaw.model.usage":
            return

        attrs = _attrs_dict(span.attributes)
        session_id = str(attrs.get("openclaw.sessionId", ""))
        if not session_id:
            return

        start_ns = span.start_time_unix_nano
        end_ns = span.end_time_unix_nano
        duration_ms = (end_ns - start_ns) / 1_000_000 if end_ns > start_ns else 0

        ts = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=UTC).isoformat()

        session_key = str(attrs.get("openclaw.sessionKey", ""))
        agent = _agent_from_session_key(session_key) or str(attrs.get("openclaw.channel", ""))

        record = {
            "session_id": session_id,
            "agent": agent,
            "model": attrs.get("openclaw.model", ""),
            "provider": attrs.get("openclaw.provider", ""),
            "tokens": {
                "input": _safe_int(attrs.get("openclaw.tokens.input", 0)),
                "output": _safe_int(attrs.get("openclaw.tokens.output", 0)),
                "cache_read": _safe_int(attrs.get("openclaw.tokens.cache_read", 0)),
                "cache_write": _safe_int(attrs.get("openclaw.tokens.cache_write", 0)),
                "total": _safe_int(attrs.get("openclaw.tokens.total", 0)),
            },
            "duration_ms": round(duration_ms, 1),
            "timestamp": ts,
        }

        existing = self._sessions.get(session_id)
        if existing:
            existing["turns"] = existing.get("turns", 1) + 1
            existing["agent"] = record["agent"] or existing.get("agent", "")
            existing["model"] = record["model"] or existing.get("model", "")
            existing["provider"] = record["provider"] or existing.get("provider", "")
            existing["duration_ms"] = round(existing.get("duration_ms", 0) + duration_ms, 1)
            existing["timestamp"] = max(existing.get("timestamp", ""), ts)
            et = existing.get("tokens", {})
            rt = record["tokens"]
            for k in ("input", "output", "cache_read", "cache_write", "total"):
                et[k] = et.get(k, 0) + rt.get(k, 0)
            existing["tokens"] = et
        else:
            record["turns"] = 1
            self._sessions[session_id] = record
            if len(self._sessions) > _MAX_SESSIONS:
                oldest_key = min(
                    self._sessions, key=lambda k: self._sessions[k].get("timestamp", "")
                )
                del self._sessions[oldest_key]

    def _ensure_host_bucket(self, host: str) -> dict:
        """Return (and lazily create) the by-host tracking dict."""
        if host not in self._by_host:
            self._by_host[host] = {
                "tokens": _zero_tokens(),
                "cost_usd": 0.0,
                "spans": 0,
                "messages_processed": 0,
                "agents": [],
                "last_seen": "",
            }
        return self._by_host[host]

    def _track_host_metric(self, host: str, metric) -> None:
        """Accumulate per-host counters from a single OTLP metric."""
        bucket = self._ensure_host_bucket(host)
        name = metric.name
        if metric.HasField("sum"):
            for dp in metric.sum.data_points:
                attrs = _attrs_dict(dp.attributes)
                value = dp.as_double if dp.HasField("as_double") else float(dp.as_int)
                if name == "openclaw.tokens":
                    token_type = attrs.get("openclaw.token", "total")
                    if token_type in bucket["tokens"]:
                        bucket["tokens"][token_type] = value
                    agent = attrs.get("openclaw.channel", "")
                    if agent and agent not in bucket["agents"]:
                        bucket["agents"].append(agent)
                elif name == "openclaw.cost.usd":
                    bucket["cost_usd"] = value
                elif name == "openclaw.message.processed":
                    bucket["messages_processed"] = value

    def _track_host_span(self, host: str, span) -> None:
        """Accumulate per-host span counts from trace data."""
        bucket = self._ensure_host_bucket(host)
        bucket["spans"] += 1
        start_ns = span.start_time_unix_nano
        if start_ns:
            ts = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=UTC).isoformat()
            if ts > bucket["last_seen"]:
                bucket["last_seen"] = ts
        attrs = _attrs_dict(span.attributes)
        agent = str(attrs.get("openclaw.channel", ""))
        if agent and agent not in bucket["agents"]:
            bucket["agents"].append(agent)


def _agent_from_session_key(session_key: str) -> str:
    """Extract agent name from a session key like 'agent:rowan-agent:mycelium-room:...'."""
    if session_key.startswith("agent:"):
        parts = session_key.split(":", 3)
        if len(parts) >= 2:
            return parts[1]
    return ""


def _safe_int(value: str | int | float) -> int:
    """Convert a value to int, returning 0 on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _zero_tokens() -> dict:
    return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0}


def _zero_histogram() -> dict:
    return {"count": 0, "sum": 0, "min": None, "max": None}


def _merge_histogram(dst: dict, src: dict) -> None:
    """Merge ``src`` histogram into ``dst`` (sum counts/sums, min of mins,
    max of maxes). ``dst`` is mutated in place; missing fields default to
    a zero histogram so it is safe to call with sparse data.
    """
    if not src:
        return
    dst["count"] = dst.get("count", 0) + (src.get("count") or 0)
    dst["sum"] = dst.get("sum", 0) + (src.get("sum") or 0)
    src_min = src.get("min")
    if src_min is not None:
        dst["min"] = src_min if dst.get("min") is None else min(dst["min"], src_min)
    src_max = src.get("max")
    if src_max is not None:
        dst["max"] = src_max if dst.get("max") is None else max(dst["max"], src_max)


def _sanitize_for_json(obj: object) -> object:
    """Recursively replace float inf/nan with None so output is valid JSON."""
    import math

    if isinstance(obj, float):
        return None if (math.isinf(obj) or math.isnan(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _json_default(obj: object) -> object:
    """json.dumps default handler: coerce non-serializable types to str."""
    return str(obj)


def _attrs_dict(attributes) -> dict[str, str | int | float | bool]:
    """Convert protobuf KeyValue list to a plain dict."""
    result: dict[str, str | int | float | bool] = {}
    for kv in attributes:
        v = kv.value
        if v.HasField("string_value"):
            result[kv.key] = v.string_value
        elif v.HasField("int_value"):
            result[kv.key] = v.int_value
        elif v.HasField("double_value"):
            result[kv.key] = v.double_value
        elif v.HasField("bool_value"):
            result[kv.key] = v.bool_value
    return result


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge *override* into *base*, preserving keys that only exist in base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _fetch_backend_metrics(
    store: MetricsStore, api_url: str, output_path: Path | None = None
) -> None:
    """Poll the Mycelium backend /api/observability endpoint (best-effort).

    If output_path is provided, persist the updated metrics to disk.
    """
    import urllib.request

    try:
        req = urllib.request.Request(f"{api_url}/api/observability", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            store.set_backend_metrics(data)
            log.info("Backend metrics polled OK (%d counters)", len(data.get("counters", {})))

            if output_path is not None:
                try:
                    full_data = _sanitize_for_json(store.to_dict())
                    tmp = output_path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(full_data, indent=2, default=_json_default))
                    tmp.replace(output_path)
                except Exception as write_exc:
                    log.debug("Failed to persist metrics: %s", write_exc)
    except Exception as exc:
        log.warning("Backend metrics poll failed (%s): %s", api_url, exc)


def _fetch_scrape_targets(
    store: MetricsStore,
    targets: list[dict],
    output_path: Path | None = None,
) -> None:
    """Scrape each configured Prometheus target and roll it up.

    ``targets`` is a list of ``{"name": str, "url": str, "kind": str}``
    dicts (kind defaults to "http_red" for stock fastapi-instrumentator
    output). On any per-target failure we record the failure into the store
    so the panel can show "degraded" rather than the user wondering why a
    target dropped silently.
    """
    if not targets:
        return

    # Imported lazily so unit tests on this module don't pull in prom_scrape
    # unless they exercise this path.
    from mycelium import prom_scrape

    for t in targets:
        name = t.get("name") or t.get("url", "<unnamed>")
        url = t.get("url")
        if not url:
            continue
        kind = t.get("kind", "http_red")

        samples = prom_scrape.scrape(url, timeout=5.0)
        if samples is None:
            store.set_scrape_target(name, None)
            continue
        if kind == "http_red":
            rolled = prom_scrape.aggregate_http_red(samples)
        elif kind == "grpc_red":
            rolled = prom_scrape.aggregate_grpc_red(samples)
        else:
            log.warning("Unknown scrape kind %r for target %r, storing raw count only", kind, name)
            rolled = {"raw_sample_count": len(samples)}
        store.set_scrape_target(name, rolled)

    if output_path is not None:
        try:
            full_data = _sanitize_for_json(store.to_dict())
            tmp = output_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(full_data, indent=2, default=_json_default))
            tmp.replace(output_path)
        except Exception as write_exc:
            log.debug("Failed to persist scrape data: %s", write_exc)


class _HubForwarder:
    """Fire-and-forget OTLP forwarder from spoke collector to hub.

    Implements the agent-to-gateway pattern: every OTLP payload accepted
    locally is also POSTed to the hub collector so it can maintain a
    unified cross-host view (by_host metrics, traces).  Failures are
    logged but never block the local ingest path.

    Uses a bounded thread pool (4 workers) to prevent unbounded thread
    accumulation when the hub is slow or unreachable.
    """

    def __init__(self, hub_url: str) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._base = hub_url.rstrip("/")
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hub-fwd")
        log.info("Hub forwarding enabled → %s", self._base)

    def forward(self, path: str, body: bytes, content_type: str) -> None:
        """POST *body* to hub_url+path via the thread pool."""
        self._pool.submit(self._send, path, body, content_type)

    def _send(self, path: str, body: bytes, content_type: str) -> None:
        url = f"{self._base}{path}"
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                resp.read()
            log.debug("Forwarded %s (%d bytes) to hub", path, len(body))
        except Exception as exc:
            log.debug("Hub forward failed for %s: %s", path, exc)


class OTLPHandler(BaseHTTPRequestHandler):
    """HTTP handler for OTLP protobuf endpoints."""

    store: MetricsStore
    trace_store: TraceStore
    output_path: Path
    backend_api_url: str
    hub_forwarder: _HubForwarder | None

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response({"status": "ok"})
            return

        if self.path == "/collector/metrics":
            data = self.store.to_dict()
            self._json_response(data)
            return

        if self.path == "/collector/hosts":
            hosts = self.trace_store.get_hosts()
            self._json_response({"hosts": hosts})
            return

        if self.path.startswith("/collector/traces"):
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            try:
                limit = int(qs.get("limit", ["100"])[0])
            except (ValueError, TypeError):
                limit = 100
            limit = max(1, min(limit, _MAX_TRACES))
            host_filter = qs.get("host", [None])[0]
            traces = self.trace_store.get_recent_traces(limit, host=host_filter)
            self._json_response({"count": len(traces), "traces": traces})
            return

        self.send_response(404)
        self.end_headers()

    def _json_response(self, data: dict, status: int = 200) -> None:
        body = json.dumps(_sanitize_for_json(data), default=_json_default).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            cl_header = self.headers.get("Content-Length")
            if cl_header is not None:
                try:
                    content_length = int(cl_header)
                except ValueError:
                    self.send_response(400)
                    self.end_headers()
                    return
                if content_length < 0 or content_length > _MAX_BODY_BYTES:
                    self.send_response(413)
                    self.end_headers()
                    return
                body = self.rfile.read(content_length) if content_length > 0 else b""
            elif self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                chunks: list[bytes] = []
                total = 0
                while True:
                    size_line = self.rfile.readline().strip()
                    try:
                        chunk_size = int(size_line, 16)
                    except ValueError:
                        self.send_response(400)
                        self.end_headers()
                        return
                    if chunk_size == 0:
                        self.rfile.readline()
                        break
                    total += chunk_size
                    if total > _MAX_BODY_BYTES:
                        self.send_response(413)
                        self.end_headers()
                        return
                    chunks.append(self.rfile.read(chunk_size))
                    self.rfile.readline()
                body = b"".join(chunks)
            else:
                log.warning(
                    "POST %s: no Content-Length or chunked encoding, assuming empty body", self.path
                )
                body = b""
        except Exception:
            log.warning("Failed to read request body for %s", self.path)
            self.send_response(400)
            self.end_headers()
            return

        if self.headers.get("Content-Encoding", "").lower() == "gzip":
            try:
                dec = gzip.decompress(body)
            except Exception:
                log.warning("gzip decompress failed for %s", self.path)
                self.send_response(400)
                self.end_headers()
                return
            if len(dec) > _MAX_BODY_BYTES:
                log.warning("Decompressed body exceeds %d bytes for %s", _MAX_BODY_BYTES, self.path)
                self.send_response(413)
                self.end_headers()
                return
            body = dec

        log.debug("POST %s  %d bytes", self.path, len(body))

        if self.path not in ("/v1/metrics", "/v1/traces", "/v1/logs"):
            log.warning("Unexpected POST path %s, returning 400", self.path)
            self.send_response(400)
            self.end_headers()
            return

        ct = (self.headers.get("Content-Type") or "").lower()
        is_json = "json" in ct

        source_ip = self.client_address[0] if self.client_address else ""
        if source_ip == "::1" or source_ip == "::ffff:127.0.0.1":
            source_ip = "127.0.0.1"
        elif source_ip.startswith("::ffff:"):
            source_ip = source_ip[7:]

        try:
            if self.path == "/v1/metrics":
                self.store.ingest_metrics(body, is_json=is_json, source_ip=source_ip)
            elif self.path == "/v1/traces":
                self.store.ingest_traces(body, is_json=is_json, source_ip=source_ip)
                self.trace_store.ingest_traces(body, is_json=is_json, source_ip=source_ip)
            elif self.path == "/v1/logs":
                log.debug("Received OTLP logs (%d bytes), ack-only", len(body))
            self._flush()

            if self.hub_forwarder and self.path in ("/v1/metrics", "/v1/traces"):
                self.hub_forwarder.forward(self.path, body, ct or "application/x-protobuf")
        except Exception:
            log.exception("Failed to process %s", self.path)
            self.send_response(500)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def _flush(self) -> None:
        try:
            _ensure_shared_dir(self.output_path.parent)
            data = _sanitize_for_json(self.store.to_dict())
            tmp = self.output_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=_json_default))
            tmp.replace(self.output_path)
        except Exception as exc:
            log.warning("Failed to flush metrics to %s: %s", self.output_path, exc)

    def log_message(self, format, *args) -> None:  # noqa: A002
        log.debug(format, *args)


def _is_local_url(url: str) -> bool:
    """Return True if the URL points to a local/hub address.

    Recognizes localhost variants and the Docker Compose service name
    used when the collector runs alongside the backend in the same stack.
    """
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "mycelium-backend")


def run(
    port: int,
    output_path: Path,
    *,
    backend_api_url: str = "http://localhost:8000",
    scrape_targets: list[dict] | None = None,
    no_backend: bool = False,
    hub_url: str | None = None,
) -> None:
    """Start the OTLP HTTP receiver. Blocks until interrupted.

    ``scrape_targets`` is a list of ``{"name": str, "url": str, "kind": str}``
    dicts loaded from ``[[metrics.scrape]]`` in ``~/.mycelium/config.toml``.
    Targets are polled on the same 30-second interval as the backend.

    When ``no_backend`` is True the collector skips backend polling and
    Prometheus scraping entirely; it only accepts OTLP pushes.  This is
    the mode used on spoke nodes that run a lightweight local collector
    for OpenClaw telemetry only.

    ``hub_url``, when set, enables the agent-to-gateway forwarding pattern:
    every OTLP /v1/metrics and /v1/traces payload accepted locally is also
    POSTed (fire-and-forget) to the hub collector so it can aggregate
    cross-host data.
    """
    store = MetricsStore()
    traces_db = output_path.parent / "traces.db"
    trace_store = TraceStore(traces_db)
    scrape_targets = list(scrape_targets or [])
    if no_backend:
        is_hub = False
        scrape_targets = []
        log.info("Running in --no-backend mode: backend polling and scraping disabled")
    else:
        is_hub = _is_local_url(backend_api_url)
    if not is_hub and not no_backend:
        log.info(
            "Running as spoke (backend %s is non-local) -- backend metrics polling disabled",
            backend_api_url,
        )

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text())
            # Prefer the per-host buckets when present (post-aggregation
            # snapshots). Each host's bucket holds its own cumulative
            # values, so reloading them as-is keeps the rollup honest
            # even as live hosts push their next sample. Older snapshots
            # only have the aggregated ``counters`` field; fall back to
            # bucketing those under a synthetic ``"persisted"`` key so
            # we don't lose data outright. This may cause a one-time
            # over-count for hosts that immediately push again, but it
            # is bounded to the contents of the prior aggregated total.
            counters_by_host = existing.get("counters_by_host") or {}
            if counters_by_host:
                for host_key, bucket in counters_by_host.items():
                    _deep_merge(store._ensure_counter_bucket(host_key), bucket)
            elif existing.get("counters"):
                _deep_merge(
                    store._ensure_counter_bucket("persisted"),
                    existing["counters"],
                )

            histograms_by_host = existing.get("histograms_by_host") or {}
            if histograms_by_host:
                for host_key, bucket in histograms_by_host.items():
                    _deep_merge(store._ensure_histogram_bucket(host_key), bucket)
            elif existing.get("histograms"):
                _deep_merge(
                    store._ensure_histogram_bucket("persisted"),
                    existing["histograms"],
                )

            for s in existing.get("sessions", []):
                sid = s.get("session_id", "")
                if sid:
                    store._sessions[sid] = s
            if existing.get("backend"):
                store.set_backend_metrics(existing["backend"])
            # Preserve last-known scrape state across restarts so panels
            # don't blank out for the first poll interval after the
            # collector is restarted.
            for name, payload in (existing.get("scrape") or {}).items():
                store._scrape_targets[name] = payload
            log.info("Loaded existing data from %s", output_path)
        except Exception:
            log.warning("Could not load existing %s, starting fresh", output_path)

    forwarder = _HubForwarder(hub_url) if hub_url else None

    handler = type(
        "Handler",
        (OTLPHandler,),
        {
            "store": store,
            "trace_store": trace_store,
            "output_path": output_path,
            "backend_api_url": backend_api_url,
            "hub_forwarder": forwarder,
        },
    )

    _ensure_shared_dir(output_path.parent)

    # Periodically poll backend metrics + Prometheus scrape targets in
    # one background thread; both share the same 30-second cadence.
    # In spoke mode, skip backend polling (sensitive hub-wide data).
    _stop_event = threading.Event()

    def _backend_poller() -> None:
        while not _stop_event.wait(30):
            if is_hub:
                _fetch_backend_metrics(store, backend_api_url, output_path)
            _fetch_scrape_targets(store, scrape_targets, output_path)
            trace_store.cleanup_old_spans()

    poller = threading.Thread(target=_backend_poller, daemon=True)
    poller.start()
    if is_hub:
        _fetch_backend_metrics(store, backend_api_url, output_path)
    _fetch_scrape_targets(store, scrape_targets, output_path)
    if scrape_targets:
        log.info(
            "Configured %d Prometheus scrape target(s): %s",
            len(scrape_targets),
            ", ".join(t.get("name", t.get("url", "?")) for t in scrape_targets),
        )

    class _DualStackHTTPServer(HTTPServer):
        address_family = socket.AF_INET6
        allow_reuse_address = True

        def server_bind(self) -> None:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            super().server_bind()

    try:
        server = _DualStackHTTPServer(("::", port), handler)
    except OSError as exc:
        if exc.errno == 98:  # EADDRINUSE
            log.error("Port %d is already in use; is another collector running?", port)
            raise SystemExit(1) from exc
        server = HTTPServer(("", port), handler)
    log.info("OTLP receiver listening on :%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        server.server_close()
        if is_hub:
            _fetch_backend_metrics(store, backend_api_url, output_path)
        data = _sanitize_for_json(store.to_dict())
        tmp = output_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=_json_default))
        tmp.replace(output_path)
        trace_store.cleanup_old_spans()
        log.info("Final state saved to %s; traces in %s", output_path, traces_db)
