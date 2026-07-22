# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Regression test for ``TraceStore.get_hosts()``'s per-host agent list.

Guards against reading ``openclaw.channel`` (the channel *kind* — e.g.
mycelium-room, matrix — set by diagnostics-otel on every model-usage span)
where ``openclaw.agent`` (the real per-agent id, set on the same span) was
intended. Feeds the UI's "Spoke Sites" table, which showed channel names in
its AGENTS column instead of agent handles.
"""

from __future__ import annotations

from mycelium.collector import TraceStore


def _make_span_request(*, agent: str, channel: str) -> bytes:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
    from opentelemetry.proto.resource.v1.resource_pb2 import Resource

    req = ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    rs.resource.CopyFrom(Resource())
    kv = KeyValue()
    kv.key = "host.name"
    kv.value.CopyFrom(AnyValue(string_value="oclw-3"))
    rs.resource.attributes.append(kv)

    ss = rs.scope_spans.add()
    span = ss.spans.add()
    span.name = "openclaw.agent.turn"
    for key, value in (("openclaw.agent", agent), ("openclaw.channel", channel)):
        attr = KeyValue()
        attr.key = key
        attr.value.CopyFrom(AnyValue(string_value=value))
        span.attributes.append(attr)

    return req.SerializeToString()


def test_get_hosts_reports_agent_not_channel(tmp_path) -> None:
    store = TraceStore(tmp_path / "traces.db")
    store.ingest_traces(_make_span_request(agent="agent-alpha", channel="mycelium-room"))

    hosts = store.get_hosts()
    assert len(hosts) == 1
    assert hosts[0]["host"] == "oclw-3"
    assert hosts[0]["agents"] == ["agent-alpha"]


def test_get_hosts_channel_only_span_reports_no_agent(tmp_path) -> None:
    """A span with only openclaw.channel (no openclaw.agent) must not surface
    the channel name as if it were an agent."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
    from opentelemetry.proto.resource.v1.resource_pb2 import Resource

    req = ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    rs.resource.CopyFrom(Resource())
    host_kv = KeyValue()
    host_kv.key = "host.name"
    host_kv.value.CopyFrom(AnyValue(string_value="oclw-3"))
    rs.resource.attributes.append(host_kv)
    ss = rs.scope_spans.add()
    span = ss.spans.add()
    span.name = "some.span"
    kv = KeyValue()
    kv.key = "openclaw.channel"
    kv.value.CopyFrom(AnyValue(string_value="mycelium-room"))
    span.attributes.append(kv)

    store = TraceStore(tmp_path / "traces.db")
    store.ingest_traces(req.SerializeToString())

    hosts = store.get_hosts()
    assert len(hosts) == 1
    assert hosts[0]["agents"] == []
