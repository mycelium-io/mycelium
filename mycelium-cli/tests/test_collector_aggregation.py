# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What the collector keeps about the hosts that send it OTLP data.

Each host gets one entry: how many spans and metric points it has sent, when
it was last heard from, and the agents its spans name (read from the GenAI
semantic-convention attributes). The trace store reports the same agents per
host. Built from real OTLP protobufs, so the parsing path is exercised too.
"""

from __future__ import annotations

from pathlib import Path

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import Metric, NumberDataPoint

from mycelium.collector import MetricsStore, TraceStore

_NS = 1_700_000_000_000_000_000


def _kv(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))


def _traces(host: str, *agents: str) -> bytes:
    req = ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    rs.resource.attributes.append(_kv("host.name", host))
    ss = rs.scope_spans.add()
    for i, agent in enumerate(agents):
        span = ss.spans.add()
        span.trace_id = bytes([i + 1]) * 16
        span.span_id = bytes([i + 1]) * 8
        span.name = "chat"
        span.start_time_unix_nano = _NS + i
        span.end_time_unix_nano = _NS + i + 1_000_000
        if agent:
            span.attributes.append(_kv("gen_ai.agent.name", agent))
    return req.SerializeToString()


def _metrics(host: str, points: int) -> bytes:
    req = ExportMetricsServiceRequest()
    rm = req.resource_metrics.add()
    rm.resource.attributes.append(_kv("host.name", host))
    metric = Metric(name="gen_ai.client.token.usage")
    for n in range(points):
        metric.sum.data_points.append(NumberDataPoint(as_int=n))
    rm.scope_metrics.add().metrics.append(metric)
    return req.SerializeToString()


def test_each_host_gets_its_spans_and_agents() -> None:
    store = MetricsStore()
    store.ingest_traces(_traces("build-1", "agent-1", "agent-2", "agent-1"))
    store.ingest_traces(_traces("build-2", "agent-3"))

    by_host = store.to_dict()["by_host"]
    assert by_host["build-1"]["spans"] == 3
    assert by_host["build-1"]["agents"] == ["agent-1", "agent-2"]
    assert by_host["build-2"]["agents"] == ["agent-3"]
    assert by_host["build-1"]["last_seen"]


def test_a_span_that_names_no_agent_still_counts() -> None:
    store = MetricsStore()
    store.ingest_traces(_traces("build-1", ""))

    host = store.to_dict()["by_host"]["build-1"]
    assert host["spans"] == 1
    assert host["agents"] == []


def test_metric_points_are_counted_per_host() -> None:
    store = MetricsStore()
    store.ingest_metrics(_metrics("build-1", 4))
    store.ingest_metrics(_metrics("build-1", 2))

    assert store.to_dict()["by_host"]["build-1"]["metric_points"] == 6


def test_a_push_with_no_host_falls_back_to_the_sender_address() -> None:
    store = MetricsStore()
    req = ExportTraceServiceRequest()
    span = req.resource_spans.add().scope_spans.add().spans.add()
    span.trace_id = b"\x01" * 16
    span.span_id = b"\x01" * 8
    span.name = "chat"
    span.start_time_unix_nano = _NS

    store.ingest_traces(req.SerializeToString(), source_ip="10.0.0.7")

    assert store.to_dict()["by_host"]["10.0.0.7"]["spans"] == 1


def test_the_snapshot_holds_only_what_was_collected() -> None:
    store = MetricsStore()
    assert set(store.to_dict()) == {"updated_at"}

    store.set_backend_metrics({"counters": {"llm": {"calls": 3}}})
    snapshot = store.to_dict()
    assert snapshot["backend"]["counters"]["llm"]["calls"] == 3
    assert "counters" not in snapshot
    assert "sessions" not in snapshot


def test_the_trace_store_lists_each_hosts_agents(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "traces.db")
    traces.ingest_traces(_traces("build-1", "agent-1", "agent-2"))

    hosts = traces.get_hosts()
    assert [h["host"] for h in hosts] == ["build-1"]
    assert hosts[0]["agents"] == ["agent-1", "agent-2"]
    assert traces.get_recent_traces()[0]["agent"] in {"agent-1", "agent-2"}
