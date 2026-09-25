# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The metrics collector: backend counters, Prometheus scrapes, and OTLP traces.

On the hub it polls the backend's ``/api/observability`` counters and any
configured Prometheus targets every 30 seconds, and writes them to a JSON
file. It also accepts OTLP data on ``/v1/traces`` and ``/v1/metrics`` from
anything pointed at it: traces go to a SQLite store, and each sending host is
tracked (spans, last seen, agent names).

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


_MAX_TRACES = 500

#: Span attributes that name the agent a span belongs to, most specific first
#: (OpenTelemetry's GenAI semantic conventions).
_AGENT_ATTRS = ("gen_ai.agent.name", "gen_ai.agent.id", "gen_ai.agent")


def _agent_of(attrs: dict) -> str:
    """The agent a span's attributes name, or ``""``."""
    for key in _AGENT_ATTRS:
        value = attrs.get(key)
        if value:
            return str(value)
    return ""


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

                agent = next(
                    (a for a in (_agent_of(s.get("attributes", {})) for s in spans) if a), ""
                )

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

            agent_expr = (
                "COALESCE("
                + ", ".join(
                    f"NULLIF(json_extract(attributes, '$.\"{key}\"'), '')" for key in _AGENT_ATTRS
                )
                + ")"
            )
            agents_rows = conn.execute(
                f"SELECT host, {agent_expr} AS agent FROM spans "  # noqa: S608 - fixed keys
                f"WHERE host != '' AND {agent_expr} IS NOT NULL "
                "GROUP BY host, agent"
            ).fetchall()

            agents_by_host: dict[str, list[str]] = {}
            for row in agents_rows:
                agents_by_host.setdefault(row[0], []).append(str(row[1]))

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
    """What the collector knows: backend counters, scrape results, and hosts sending OTLP."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._backend_metrics: dict | None = None
        # One entry per host that has sent OTLP data: spans and metric
        # points received, when it was last heard from, and the agents its
        # spans named.
        self._by_host: dict[str, dict] = {}
        # Per-target Prometheus scrape state, keyed by config-supplied name.
        # Populated by `_fetch_scrape_targets` in the collector poller thread.
        self._scrape_targets: dict[str, dict] = {}

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
            result: dict = {"updated_at": datetime.now(UTC).isoformat()}
            if self._backend_metrics:
                result["backend"] = copy.deepcopy(self._backend_metrics)
            if self._scrape_targets:
                result["scrape"] = copy.deepcopy(self._scrape_targets)
            if self._by_host:
                result["by_host"] = copy.deepcopy(self._by_host)
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
                if not host:
                    continue
                points = sum(
                    len(getattr(metric, kind).data_points)
                    for sm in rm.scope_metrics
                    for metric in sm.metrics
                    for kind in ("sum", "gauge", "histogram")
                    if metric.HasField(kind)
                )
                bucket = self._ensure_host_bucket(host)
                bucket["metric_points"] += points
                bucket["last_seen"] = max(bucket["last_seen"], datetime.now(UTC).isoformat())

    def ingest_traces(
        self, request_bytes: bytes, *, is_json: bool = False, source_ip: str = ""
    ) -> None:
        """Count each host's spans and note the agents they name.

        The spans themselves are stored by ``TraceStore``; this only keeps
        the per-host summary.
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
                if not host:
                    continue
                for ss in rs.scope_spans:
                    for span in ss.spans:
                        self._track_host_span(host, span)

    def _ensure_host_bucket(self, host: str) -> dict:
        """Return (and lazily create) the by-host tracking dict."""
        if host not in self._by_host:
            self._by_host[host] = {
                "spans": 0,
                "metric_points": 0,
                "agents": [],
                "last_seen": "",
            }
        bucket = self._by_host[host]
        # A bucket reloaded from an older snapshot may lack newer fields.
        bucket.setdefault("spans", 0)
        bucket.setdefault("metric_points", 0)
        bucket.setdefault("agents", [])
        bucket.setdefault("last_seen", "")
        return bucket

    def _track_host_span(self, host: str, span) -> None:
        """Count a span against its host, and note the agent it names."""
        bucket = self._ensure_host_bucket(host)
        bucket["spans"] += 1
        start_ns = span.start_time_unix_nano
        if start_ns:
            ts = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=UTC).isoformat()
            if ts > bucket["last_seen"]:
                bucket["last_seen"] = ts
        agent = _agent_of(_attrs_dict(span.attributes))
        if agent and agent not in bucket["agents"]:
            bucket["agents"].append(agent)


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
    the mode used on spoke nodes that run a local collector for their own
    traces.

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
            for host_key, bucket in (existing.get("by_host") or {}).items():
                _deep_merge(
                    store._ensure_host_bucket(host_key),
                    {
                        k: v
                        for k, v in bucket.items()
                        if k in ("spans", "metric_points", "agents", "last_seen")
                    },
                )
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
