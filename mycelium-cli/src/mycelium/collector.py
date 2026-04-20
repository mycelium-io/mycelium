"""
Lightweight OTLP HTTP receiver for OpenClaw telemetry.

Accepts protobuf-encoded OTLP data on /v1/traces and /v1/metrics,
aggregates counters/histograms/sessions in memory, and persists to a JSON file.

Designed to be run as a background process via `mycelium metrics collect`.
"""

from __future__ import annotations

import copy
import gzip
import json
import logging
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

log = logging.getLogger(__name__)

_MAX_SESSIONS = 200
_MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MiB guard against oversized payloads


class MetricsStore:
    """In-memory aggregation of OTLP counters, histograms, and session records."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._counters: dict = {
            "tokens": {"by_agent": {}, "by_model": {}, "total": _zero_tokens()},
            "cost_usd": {"by_agent": {}, "by_model": {}, "total": 0.0},
            "messages": {"processed": 0, "queued": 0},
            "webhooks": {"received": 0, "errors": 0},
            "lanes": {"enqueue": 0, "dequeue": 0},
            "sessions_state": {},
            "sessions_stuck": 0,
            "run_attempts": 0,
        }
        self._histograms: dict = {
            "run_duration_ms": _zero_histogram(),
            "message_duration_ms": _zero_histogram(),
            "queue_depth": _zero_histogram(),
            "queue_wait_ms": _zero_histogram(),
            "context_tokens": _zero_histogram(),
            "webhook_duration_ms": _zero_histogram(),
            "session_stuck_age_ms": _zero_histogram(),
            "by_agent": {},
        }
        self._sessions: dict[str, dict] = {}
        self._backend_metrics: dict | None = None
        # Per-target Prometheus scrape state, keyed by config-supplied name.
        # Populated by `_fetch_scrape_targets` in the collector poller thread.
        self._scrape_targets: dict[str, dict] = {}

    def set_backend_metrics(self, data: dict | None) -> None:
        with self.lock:
            self._backend_metrics = data

    def set_scrape_target(self, name: str, data: dict | None) -> None:
        """Record the latest scrape result for a Prometheus target by name.

        ``data`` is the rolled-up dict from
        ``prom_scrape.aggregate_http_red(...)`` — see that helper for shape.
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
                "counters": copy.deepcopy(self._counters),
                "histograms": copy.deepcopy(self._histograms),
                "sessions": copy.deepcopy(sessions),
            }
            if self._backend_metrics:
                result["backend"] = copy.deepcopy(self._backend_metrics)
            if self._scrape_targets:
                result["scrape"] = copy.deepcopy(self._scrape_targets)
            return result

    def ingest_metrics(self, request_bytes: bytes) -> None:
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
            ExportMetricsServiceRequest,
        )

        msg = ExportMetricsServiceRequest()
        msg.ParseFromString(request_bytes)

        with self.lock:
            for rm in msg.resource_metrics:
                for sm in rm.scope_metrics:
                    for metric in sm.metrics:
                        self._process_metric(metric)

    def ingest_traces(self, request_bytes: bytes) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        msg = ExportTraceServiceRequest()
        msg.ParseFromString(request_bytes)

        with self.lock:
            for rs in msg.resource_spans:
                for ss in rs.scope_spans:
                    for span in ss.spans:
                        self._process_span(span)

    def _process_metric(self, metric) -> None:  # noqa: C901
        name = metric.name

        if metric.HasField("sum"):
            for dp in metric.sum.data_points:
                attrs = _attrs_dict(dp.attributes)
                value = dp.as_double if dp.HasField("as_double") else float(dp.as_int)

                if name == "openclaw.tokens":
                    token_type = attrs.get("openclaw.token", "total")
                    agent = attrs.get("openclaw.channel", "")
                    model = attrs.get("openclaw.model", "")

                    if token_type in self._counters["tokens"]["total"]:
                        self._counters["tokens"]["total"][token_type] = value

                    if agent:
                        bucket = self._counters["tokens"]["by_agent"].setdefault(
                            agent, _zero_tokens()
                        )
                        if token_type in bucket:
                            bucket[token_type] = value

                    if model:
                        bucket = self._counters["tokens"]["by_model"].setdefault(
                            model, _zero_tokens()
                        )
                        if token_type in bucket:
                            bucket[token_type] = value

                elif name == "openclaw.cost.usd":
                    agent = attrs.get("openclaw.channel", "")
                    model = attrs.get("openclaw.model", "")
                    self._counters["cost_usd"]["total"] = value
                    if agent:
                        self._counters["cost_usd"]["by_agent"][agent] = value
                    if model:
                        self._counters["cost_usd"]["by_model"][model] = value

                elif name == "openclaw.message.processed":
                    self._counters["messages"]["processed"] = value

                elif name == "openclaw.message.queued":
                    self._counters["messages"]["queued"] = value

                elif name == "openclaw.webhook.received":
                    self._counters["webhooks"]["received"] = value

                elif name == "openclaw.webhook.error":
                    self._counters["webhooks"]["errors"] = value

                elif name == "openclaw.queue.lane.enqueue":
                    self._counters["lanes"]["enqueue"] = value

                elif name == "openclaw.queue.lane.dequeue":
                    self._counters["lanes"]["dequeue"] = value

                elif name == "openclaw.session.state":
                    state = attrs.get("openclaw.state", "unknown")
                    self._counters["sessions_state"][state] = value

                elif name == "openclaw.session.stuck":
                    self._counters["sessions_stuck"] = value

                elif name == "openclaw.run.attempt":
                    self._counters["run_attempts"] = value

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
                    self._histograms[key] = update
                    agent = attrs.get("openclaw.channel", "")
                    if agent:
                        agent_h = self._histograms["by_agent"].setdefault(agent, {})
                        agent_h[key] = update

    def _process_span(self, span) -> None:
        if span.name != "openclaw.model.usage":
            return

        attrs = _attrs_dict(span.attributes)
        session_id = attrs.get("openclaw.sessionId", "")
        if not session_id:
            return

        start_ns = span.start_time_unix_nano
        end_ns = span.end_time_unix_nano
        duration_ms = (end_ns - start_ns) / 1_000_000 if end_ns > start_ns else 0

        ts = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=UTC).isoformat()

        session_key = attrs.get("openclaw.sessionKey", "")
        agent = _agent_from_session_key(session_key) or attrs.get("openclaw.channel", "")

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


def _agent_from_session_key(session_key: str) -> str:
    """Extract agent name from a session key like 'agent:selina-agent:matrix:...'."""
    if session_key.startswith("agent:"):
        parts = session_key.split(":", 3)
        if len(parts) >= 2:
            return parts[1]
    return ""


def _safe_int(value: object) -> int:
    """Convert a value to int, returning 0 on failure."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return 0


def _zero_tokens() -> dict:
    return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0}


def _zero_histogram() -> dict:
    return {"count": 0, "sum": 0, "min": None, "max": None}


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


def _fetch_backend_metrics(store: MetricsStore, api_url: str, output_path: Path | None = None) -> None:
    """Poll the Mycelium backend /api/metrics endpoint (best-effort).

    If output_path is provided, persist the updated metrics to disk.
    """
    import urllib.request

    try:
        req = urllib.request.Request(f"{api_url}/api/metrics", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            store.set_backend_metrics(data)

            # Persist to disk if output path provided
            if output_path is not None:
                try:
                    full_data = store.to_dict()
                    tmp = output_path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(full_data, indent=2, default=str))
                    tmp.replace(output_path)
                except Exception as write_exc:
                    log.debug("Failed to persist metrics: %s", write_exc)
    except Exception as exc:
        log.debug("Backend metrics poll failed (%s): %s", api_url, exc)


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
        else:
            # Unknown kind — preserve raw samples so we don't lose data.
            rolled = {"raw_sample_count": len(samples)}
        store.set_scrape_target(name, rolled)

    if output_path is not None:
        try:
            full_data = store.to_dict()
            tmp = output_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(full_data, indent=2, default=str))
            tmp.replace(output_path)
        except Exception as write_exc:
            log.debug("Failed to persist scrape data: %s", write_exc)


class OTLPHandler(BaseHTTPRequestHandler):
    """HTTP handler for OTLP protobuf endpoints."""

    store: MetricsStore
    output_path: Path
    backend_api_url: str

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
                log.warning("POST %s: no Content-Length or chunked encoding, assuming empty body", self.path)
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

        if self.path in ("/v1/metrics", "/v1/traces"):
            try:
                if self.path == "/v1/metrics":
                    self.store.ingest_metrics(body)
                else:
                    self.store.ingest_traces(body)
                self._flush()
            except Exception:
                log.exception("Failed to process %s", self.path)
                self.send_response(500)
                self.end_headers()
                return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def _flush(self) -> None:
        data = self.store.to_dict()
        tmp = self.output_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(self.output_path)

    def log_message(self, format, *args) -> None:  # noqa: A002
        log.debug(format, *args)


def run(
    port: int,
    output_path: Path,
    *,
    backend_api_url: str = "http://localhost:8000",
    scrape_targets: list[dict] | None = None,
) -> None:
    """Start the OTLP HTTP receiver. Blocks until interrupted.

    ``scrape_targets`` is a list of ``{"name": str, "url": str, "kind": str}``
    dicts loaded from ``[[metrics.scrape]]`` in ``~/.mycelium/config.toml``.
    Targets are polled on the same 30-second interval as the backend.
    """
    store = MetricsStore()
    scrape_targets = list(scrape_targets or [])

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text())
            _deep_merge(store._counters, existing.get("counters", {}))
            _deep_merge(store._histograms, existing.get("histograms", {}))
            for s in existing.get("sessions", []):
                sid = s.get("session_id", "")
                if sid:
                    store._sessions[sid] = s
            if existing.get("backend"):
                store.set_backend_metrics(existing["backend"])
            # Preserve last-known scrape state across restarts so panels
            # don't blank out for the first poll interval after `mycelium
            # metrics collect` is restarted.
            for name, payload in (existing.get("scrape") or {}).items():
                store._scrape_targets[name] = payload
            log.info("Loaded existing data from %s", output_path)
        except Exception:
            log.warning("Could not load existing %s, starting fresh", output_path)

    handler = type(
        "Handler",
        (OTLPHandler,),
        {"store": store, "output_path": output_path, "backend_api_url": backend_api_url},
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Periodically poll backend metrics + Prometheus scrape targets in
    # one background thread; both share the same 30-second cadence.
    _stop_event = threading.Event()

    def _backend_poller() -> None:
        while not _stop_event.wait(30):
            _fetch_backend_metrics(store, backend_api_url, output_path)
            _fetch_scrape_targets(store, scrape_targets, output_path)

    poller = threading.Thread(target=_backend_poller, daemon=True)
    poller.start()
    _fetch_backend_metrics(store, backend_api_url, output_path)
    _fetch_scrape_targets(store, scrape_targets, output_path)
    if scrape_targets:
        log.info(
            "Configured %d Prometheus scrape target(s): %s",
            len(scrape_targets),
            ", ".join(t.get("name", t.get("url", "?")) for t in scrape_targets),
        )

    server = HTTPServer(("127.0.0.1", port), handler)
    log.info("OTLP receiver listening on :%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        server.server_close()
        _fetch_backend_metrics(store, backend_api_url, output_path)
        data = store.to_dict()
        tmp = output_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(output_path)
        log.info("Final state saved to %s", output_path)
