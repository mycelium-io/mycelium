"""
Lightweight OTLP HTTP receiver for OpenClaw telemetry.

Accepts protobuf-encoded OTLP data on /v1/traces, /v1/metrics, and /v1/logs,
aggregates counters/histograms/sessions in memory, and persists to a JSON file.

Designed to be run as a background process via `mycelium metrics collect`.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

log = logging.getLogger(__name__)

_MAX_SESSIONS = 200


class MetricsStore:
    """In-memory aggregation of OTLP counters, histograms, and session records."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._counters: dict = {
            "tokens": {"by_agent": {}, "by_model": {}, "total": _zero_tokens()},
            "cost_usd": {"by_agent": {}, "by_model": {}, "total": 0.0},
            "messages": {"processed": 0, "queued": 0},
        }
        self._histograms: dict = {
            "run_duration_ms": _zero_histogram(),
            "message_duration_ms": _zero_histogram(),
            "queue_depth": _zero_histogram(),
            "queue_wait_ms": _zero_histogram(),
            "by_agent": {},
        }
        self._sessions: dict[str, dict] = {}

    def to_dict(self) -> dict:
        with self.lock:
            sessions = sorted(
                self._sessions.values(),
                key=lambda s: s.get("timestamp", ""),
                reverse=True,
            )[:_MAX_SESSIONS]
            return {
                "updated_at": datetime.now(UTC).isoformat(),
                "counters": self._counters,
                "histograms": self._histograms,
                "sessions": sessions,
            }

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
                "input": int(attrs.get("openclaw.tokens.input", 0)),
                "output": int(attrs.get("openclaw.tokens.output", 0)),
                "cache_read": int(attrs.get("openclaw.tokens.cache_read", 0)),
                "cache_write": int(attrs.get("openclaw.tokens.cache_write", 0)),
                "total": int(attrs.get("openclaw.tokens.total", 0)),
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


class OTLPHandler(BaseHTTPRequestHandler):
    """HTTP handler for OTLP protobuf endpoints."""

    store: MetricsStore
    output_path: Path

    def do_POST(self) -> None:
        cl_header = self.headers.get("Content-Length")
        if cl_header is not None:
            content_length = int(cl_header)
            body = self.rfile.read(content_length) if content_length > 0 else b""
        elif self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            chunks = []
            while True:
                size_line = self.rfile.readline().strip()
                chunk_size = int(size_line, 16)
                if chunk_size == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(chunk_size))
                self.rfile.readline()
            body = b"".join(chunks)
        else:
            body = self.rfile.read()

        if self.headers.get("Content-Encoding", "").lower() == "gzip":
            try:
                body = gzip.decompress(body)
            except Exception:
                log.warning("gzip decompress failed for %s", self.path)
                self.send_response(400)
                self.end_headers()
                return

        log.debug("POST %s  %d bytes", self.path, len(body))

        try:
            if self.path == "/v1/metrics":
                self.store.ingest_metrics(body)
                self._flush()
            elif self.path == "/v1/traces":
                self.store.ingest_traces(body)
                self._flush()
        except Exception:
            log.exception("Failed to process %s", self.path)

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


def run(port: int, output_path: Path) -> None:
    """Start the OTLP HTTP receiver. Blocks until interrupted."""
    store = MetricsStore()

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text())
            store._counters = existing.get("counters", store._counters)
            store._histograms = existing.get("histograms", store._histograms)
            for s in existing.get("sessions", []):
                sid = s.get("session_id", "")
                if sid:
                    store._sessions[sid] = s
            log.info("Loaded existing data from %s", output_path)
        except Exception:
            log.warning("Could not load existing %s, starting fresh", output_path)

    handler = type("Handler", (OTLPHandler,), {"store": store, "output_path": output_path})

    output_path.parent.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("127.0.0.1", port), handler)
    log.info("OTLP receiver listening on :%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        data = store.to_dict()
        output_path.write_text(json.dumps(data, indent=2, default=str))
        log.info("Final state saved to %s", output_path)
