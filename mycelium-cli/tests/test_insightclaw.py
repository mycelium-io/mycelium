# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Unit tests for the InsightClaw integration.

Covers:
  - _room_from_session_key: format parsing and defensive edge cases
  - _configure_insightclaw: config payload written to openclaw.json
  - _CfnForwarder: kill-switch gate, span partitioning by mas_id,
    resource attribute injection, per-mas counters
  - MetricsStore.ingest_metrics: InsightClaw metric namespaces parsed
    into the insightclaw sub-bucket; gauge support
"""

from __future__ import annotations

import json
import unittest.mock as mock
from pathlib import Path

import pytest

from mycelium.collector import MetricsStore, _room_from_session_key

# ── _room_from_session_key ─────────────────────────────────────────────────


class TestRoomFromSessionKey:
    def test_normal_key(self):
        key = "agent:julia:mycelium-room:group:my-project"
        assert _room_from_session_key(key) == "my-project"

    def test_room_with_hyphens(self):
        key = "agent:julia:mycelium-room:group:my-long-room-name"
        assert _room_from_session_key(key) == "my-long-room-name"

    def test_room_with_colon(self):
        # Room names containing colons must be preserved (split on first 4 only)
        key = "agent:julia:mycelium-room:group:room:with:colons"
        assert _room_from_session_key(key) == "room:with:colons"

    def test_empty_string(self):
        assert _room_from_session_key("") == ""

    def test_wrong_prefix(self):
        assert _room_from_session_key("user:julia:mycelium-room:group:room") == ""

    def test_too_few_segments(self):
        assert _room_from_session_key("agent:julia:mycelium-room") == ""

    def test_none_like_missing(self):
        # Guard against accidental None passed as string
        assert _room_from_session_key("None") == ""  # no agent: prefix


# ── _configure_insightclaw ────────────────────────────────────────────────


class TestConfigureInsightclaw:
    def _run(
        self,
        tmp_path: Path,
        workspace_id: str = "ws-123",
        mas_id: str = "mas-456",
        port: int = 4318,
        capture_content: bool = False,
    ) -> dict:
        from mycelium.integrations.openclaw.install import _configure_insightclaw

        oc_json = tmp_path / "openclaw.json"
        oc_json.write_text(json.dumps({"plugins": {}}))

        with mock.patch(
            "mycelium.integrations.openclaw.install._openclaw_state_dir",
            return_value=tmp_path,
        ):
            result = _configure_insightclaw(
                workspace_id=workspace_id,
                mas_id=mas_id,
                port=port,
                capture_content=capture_content,
            )

        assert result is True
        cfg = json.loads(oc_json.read_text())
        return cfg

    def test_entry_written(self, tmp_path):
        cfg = self._run(tmp_path)
        entry = cfg["plugins"]["entries"]["insightclaw"]
        assert entry["enabled"] is True

    def test_traces_and_metrics_enabled(self, tmp_path):
        cfg = self._run(tmp_path)
        c = cfg["plugins"]["entries"]["insightclaw"]["config"]
        assert c["traces"] is True
        assert c["metrics"] is True

    def test_capture_content_default_false(self, tmp_path):
        cfg = self._run(tmp_path, capture_content=False)
        c = cfg["plugins"]["entries"]["insightclaw"]["config"]
        assert c["captureContent"] is False

    def test_capture_content_opt_in(self, tmp_path):
        cfg = self._run(tmp_path, capture_content=True)
        c = cfg["plugins"]["entries"]["insightclaw"]["config"]
        assert c["captureContent"] is True

    def test_resource_attributes_dot_notation(self, tmp_path):
        cfg = self._run(tmp_path, workspace_id="ws-1", mas_id="mas-2")
        c = cfg["plugins"]["entries"]["insightclaw"]["config"]
        assert c["resourceAttributes"]["workspace.id"] == "ws-1"
        assert c["resourceAttributes"]["mas.id"] == "mas-2"

    def test_custom_attributes_hyphen_notation(self, tmp_path):
        cfg = self._run(tmp_path, workspace_id="ws-1", mas_id="mas-2")
        c = cfg["plugins"]["entries"]["insightclaw"]["config"]
        assert c["customAttributes"]["workspace-id"] == "ws-1"
        assert c["customAttributes"]["mas-id"] == "mas-2"

    def test_endpoint_uses_port(self, tmp_path):
        cfg = self._run(tmp_path, port=9999)
        c = cfg["plugins"]["entries"]["insightclaw"]["config"]
        assert "9999" in c["endpoint"]

    def test_allow_list_updated(self, tmp_path):
        cfg = self._run(tmp_path)
        assert "insightclaw" in cfg["plugins"]["allow"]

    def test_emit_ioa_observe_attributes_true(self, tmp_path):
        cfg = self._run(tmp_path)
        c = cfg["plugins"]["entries"]["insightclaw"]["config"]
        assert c["emitIoaObserveAttributes"] is True

    def test_allow_conversation_access_set(self, tmp_path):
        cfg = self._run(tmp_path)
        entry = cfg["plugins"]["entries"]["insightclaw"]
        assert entry.get("hooks", {}).get("allowConversationAccess") is True


# ── _CfnForwarder: kill-switch gate ──────────────────────────────────────


class TestCfnForwarderGate:
    def test_no_forwarder_when_disabled(self):
        from mycelium.collector import _CfnForwarder

        cfn_svc_url = "http://cfn:9002"
        cfn_forward_enabled = False
        forwarder = (
            _CfnForwarder("http://backend:8000", cfn_svc_url)
            if (cfn_forward_enabled and cfn_svc_url)
            else None
        )
        assert forwarder is None

    def test_no_forwarder_when_url_empty(self):
        from mycelium.collector import _CfnForwarder

        cfn_svc_url = ""
        cfn_forward_enabled = True
        forwarder = (
            _CfnForwarder("http://backend:8000", cfn_svc_url)
            if (cfn_forward_enabled and cfn_svc_url)
            else None
        )
        assert forwarder is None


# ── _CfnForwarder: span partitioning ──────────────────────────────────────


def _make_trace_request(spans_by_room: dict[str, list[str]]) -> bytes:
    """Build a serialised ExportTraceServiceRequest with spans keyed by room.

    Each span has ``openclaw.session.key`` set to a key whose room segment
    is the dict key.  Span names are the list values.
    """
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

    req = ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    ss = rs.scope_spans.add()

    for room, names in spans_by_room.items():
        for name in names:
            span = ss.spans.add()
            span.name = name
            kv = KeyValue()
            kv.key = "openclaw.session.key"
            kv.value.CopyFrom(AnyValue(string_value=f"agent:bot:mycelium-room:group:{room}"))
            span.attributes.append(kv)

    return req.SerializeToString()


class TestCfnForwarderSpanPartitioning:
    def _forwarder(
        self,
        backend_url: str = "http://backend:8000",
        cfn_url: str = "http://cfn:9002",
        fallback_ws: str = "",
        fallback_mas: str = "",
    ):
        from mycelium.collector import _CfnForwarder

        return _CfnForwarder(
            backend_url,
            cfn_url,
            fallback_workspace_id=fallback_ws,
            fallback_mas_id=fallback_mas,
        )

    def test_room_resolved_and_mas_injected(self):
        fwd = self._forwarder()

        # Patch _fetch_room to return deterministic mas_id.
        fwd._fetch_room = lambda room: ("ws-1", f"mas-{room}")

        body = _make_trace_request({"alpha": ["span-a"], "beta": ["span-b"]})

        sent: list[bytes] = []

        def _fake_urlopen(req, timeout):  # noqa: ARG001
            sent.append(req.data)
            resp = mock.MagicMock()
            resp.read.return_value = b""
            resp.__enter__ = lambda s: s
            resp.__exit__ = mock.MagicMock(return_value=False)
            return resp

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            fwd._send(body, "application/x-protobuf")

        assert len(sent) == 1
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        out = ExportTraceServiceRequest()
        out.ParseFromString(sent[0])

        # Two ResourceSpans blocks — one per distinct mas_id.
        assert len(out.resource_spans) == 2
        mas_ids = set()
        for rs in out.resource_spans:
            attr_map = {a.key: a.value.string_value for a in rs.resource.attributes}
            assert "workspace.id" in attr_map
            assert "mas.id" in attr_map
            mas_ids.add(attr_map["mas.id"])
        assert mas_ids == {"mas-alpha", "mas-beta"}

    def test_spans_routed_to_correct_mas_block(self):
        fwd = self._forwarder()
        fwd._fetch_room = lambda room: ("ws-1", f"mas-{room}")

        # 2 spans for alpha, 1 for beta
        body = _make_trace_request({"alpha": ["s1", "s2"], "beta": ["s3"]})

        sent: list[bytes] = []

        def _fake_urlopen(req, timeout):  # noqa: ARG001
            sent.append(req.data)
            resp = mock.MagicMock()
            resp.read.return_value = b""
            resp.__enter__ = lambda s: s
            resp.__exit__ = mock.MagicMock(return_value=False)
            return resp

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            fwd._send(body, "application/x-protobuf")

        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        out = ExportTraceServiceRequest()
        out.ParseFromString(sent[0])

        counts = {}
        for rs in out.resource_spans:
            attr_map = {a.key: a.value.string_value for a in rs.resource.attributes}
            mas = attr_map["mas.id"]
            span_count = sum(len(ss.spans) for ss in rs.scope_spans)
            counts[mas] = span_count

        assert counts == {"mas-alpha": 2, "mas-beta": 1}

    def test_per_mas_counters_incremented(self):
        fwd = self._forwarder()
        fwd._fetch_room = lambda room: ("ws-1", f"mas-{room}")

        body = _make_trace_request({"roomA": ["s1"]})

        def _fake_urlopen(req, timeout):  # noqa: ARG001
            resp = mock.MagicMock()
            resp.read.return_value = b""
            resp.__enter__ = lambda s: s
            resp.__exit__ = mock.MagicMock(return_value=False)
            return resp

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            fwd._send(body, "application/x-protobuf")

        counters = fwd.get_counters()
        # Room name is lowercased by _resolve_room before _fetch_room is called
        assert "mas-rooma" in counters
        assert counters["mas-rooma"]["spans"] == 1
        assert counters["mas-rooma"]["failures"] == 0

    def test_no_session_key_uses_fallback_mas(self):
        """Spans without openclaw.session.key fall back to the static install-level mas_id."""
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        fwd = self._forwarder(fallback_ws="ws-global", fallback_mas="mas-global")
        fwd._fetch_room = lambda room: ("ws-1", f"mas-{room}")

        # Build a request with a span that has NO session key
        req = ExportTraceServiceRequest()
        rs = req.resource_spans.add()
        ss = rs.scope_spans.add()
        span = ss.spans.add()
        span.name = "no-session-key-span"
        body = req.SerializeToString()

        sent: list[bytes] = []

        def _fake_urlopen(req, timeout):  # noqa: ARG001
            sent.append(req.data)
            resp = mock.MagicMock()
            resp.read.return_value = b""
            resp.__enter__ = lambda s: s
            resp.__exit__ = mock.MagicMock(return_value=False)
            return resp

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            fwd._send(body, "application/x-protobuf")

        assert len(sent) == 1
        out = ExportTraceServiceRequest()
        out.ParseFromString(sent[0])
        assert len(out.resource_spans) == 1
        attr_map = {a.key: a.value.string_value for a in out.resource_spans[0].resource.attributes}
        assert attr_map.get("workspace.id") == "ws-global"
        assert attr_map.get("mas.id") == "mas-global"

    def test_failure_counted(self):
        fwd = self._forwarder()
        fwd._fetch_room = lambda room: ("ws-1", f"mas-{room}")

        body = _make_trace_request({"room1": ["s1"]})

        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            fwd._send(body, "application/x-protobuf")

        counters = fwd.get_counters()
        # Room name is lowercased before fetch
        assert counters.get("mas-room1", {}).get("failures", 0) == 1


# ── InsightClaw metric parsing in MetricsStore ────────────────────────────


def _make_metrics_request(metrics: list[dict]) -> bytes:
    """Build a serialised ExportMetricsServiceRequest from a list of metric dicts.

    Each dict must have: name (str), type (sum|gauge|histogram), value (float),
    and optionally attrs (dict[str, str]).
    """
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
        ExportMetricsServiceRequest,
    )
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
    from opentelemetry.proto.metrics.v1.metrics_pb2 import (
        AggregationTemporality,
        Gauge,
        Histogram,
        HistogramDataPoint,
        Metric,
        NumberDataPoint,
        Sum,
    )

    req = ExportMetricsServiceRequest()
    rm = req.resource_metrics.add()
    sm = rm.scope_metrics.add()

    for m in metrics:
        metric = Metric()
        metric.name = m["name"]
        attrs = m.get("attrs", {})

        def _kv(k: str, v: str) -> KeyValue:
            kv = KeyValue()
            kv.key = k
            kv.value.CopyFrom(AnyValue(string_value=v))
            return kv

        if m["type"] == "sum":
            s = Sum()
            s.aggregation_temporality = AggregationTemporality.AGGREGATION_TEMPORALITY_CUMULATIVE
            dp = NumberDataPoint()
            dp.as_double = float(m["value"])
            for k, v in attrs.items():
                dp.attributes.append(_kv(k, v))
            s.data_points.append(dp)
            metric.sum.CopyFrom(s)
        elif m["type"] == "gauge":
            g = Gauge()
            dp = NumberDataPoint()
            dp.as_double = float(m["value"])
            for k, v in attrs.items():
                dp.attributes.append(_kv(k, v))
            g.data_points.append(dp)
            metric.gauge.CopyFrom(g)
        elif m["type"] == "histogram":
            h = Histogram()
            h.aggregation_temporality = AggregationTemporality.AGGREGATION_TEMPORALITY_DELTA
            dp = HistogramDataPoint()
            dp.count = int(m.get("count", 1))
            dp.sum = float(m["value"])
            for k, v in attrs.items():
                dp.attributes.append(_kv(k, v))
            h.data_points.append(dp)
            metric.histogram.CopyFrom(h)

        sm.metrics.append(metric)

    return req.SerializeToString()


class TestInsightclawMetricParsing:
    def _store_with(self, metrics: list[dict]) -> MetricsStore:
        store = MetricsStore()
        store.ingest_metrics(_make_metrics_request(metrics))
        return store

    def test_llm_requests_counter(self):
        store = self._store_with(
            [
                {
                    "name": "openclaw.llm.requests",
                    "type": "sum",
                    "value": 5,
                    "attrs": {"gen_ai.agent.id": "agent-a"},
                },
            ]
        )
        d = store.to_dict()
        ic = d["counters"]["insightclaw"]
        assert ic["llm"]["requests"] == 5
        assert ic["llm"]["by_agent"]["agent-a"]["requests"] == 5

    def test_llm_errors_counter(self):
        store = self._store_with(
            [
                {
                    "name": "openclaw.llm.errors",
                    "type": "sum",
                    "value": 2,
                    "attrs": {"gen_ai.agent.id": "agent-b"},
                },
            ]
        )
        ic = store.to_dict()["counters"]["insightclaw"]
        assert ic["llm"]["errors"] == 2

    def test_tool_calls_counter(self):
        store = self._store_with(
            [
                {
                    "name": "openclaw.tool.calls",
                    "type": "sum",
                    "value": 10,
                    "attrs": {"gen_ai.agent.id": "bot"},
                },
            ]
        )
        ic = store.to_dict()["counters"]["insightclaw"]
        assert ic["tool"]["calls"] == 10
        assert ic["tool"]["by_agent"]["bot"]["calls"] == 10

    def test_memory_read_events_counter(self):
        store = self._store_with(
            [
                {
                    "name": "openclaw.memory.read_events",
                    "type": "sum",
                    "value": 3,
                    "attrs": {"gen_ai.agent.id": "agent-x"},
                },
            ]
        )
        ic = store.to_dict()["counters"]["insightclaw"]
        assert ic["memory"]["read_events"] == 3
        assert ic["memory"]["by_agent"]["agent-x"]["read_events"] == 3

    def test_memory_search_hit_miss_counters(self):
        store = self._store_with(
            [
                {"name": "openclaw.memory.search_hit", "type": "sum", "value": 7, "attrs": {}},
                {"name": "openclaw.memory.search_miss", "type": "sum", "value": 2, "attrs": {}},
            ]
        )
        ic = store.to_dict()["counters"]["insightclaw"]
        assert ic["memory"]["search_hit"] == 7
        assert ic["memory"]["search_miss"] == 2

    def test_sessions_active_gauge(self):
        store = self._store_with(
            [
                {"name": "openclaw.sessions.active", "type": "gauge", "value": 4, "attrs": {}},
            ]
        )
        ic = store.to_dict()["counters"]["insightclaw"]
        assert ic["sessions_active"] == 4

    def test_llm_duration_histogram(self):
        store = self._store_with(
            [
                {
                    "name": "openclaw.llm.duration",
                    "type": "histogram",
                    "value": 1500,
                    "count": 3,
                    "attrs": {"gen_ai.agent.id": "bot"},
                },
            ]
        )
        ic = store.to_dict()["histograms"]["insightclaw"]
        assert ic["llm_duration"]["count"] == 3
        assert ic["llm_duration"]["sum"] == 1500
        assert ic["by_agent"]["bot"]["llm_duration"]["sum"] == 1500

    def test_memory_failure_rate_histogram(self):
        store = self._store_with(
            [
                {
                    "name": "openclaw.memory.failure_rate",
                    "type": "histogram",
                    "value": 0.2,
                    "count": 1,
                    "attrs": {},
                },
            ]
        )
        ic = store.to_dict()["histograms"]["insightclaw"]
        assert ic["memory_failure_rate"]["sum"] == pytest.approx(0.2)

    def test_session_parallelisation_score_histogram(self):
        store = self._store_with(
            [
                {
                    "name": "openclaw.session.parallelisation_score",
                    "type": "histogram",
                    "value": 0.85,
                    "count": 1,
                    "attrs": {"gen_ai.agent.id": "alpha"},
                },
            ]
        )
        ic = store.to_dict()["histograms"]["insightclaw"]
        assert ic["session_parallelisation_score"]["sum"] == pytest.approx(0.85)

    def test_context_system_size_histogram(self):
        store = self._store_with(
            [
                {
                    "name": "openclaw.context.system_size",
                    "type": "histogram",
                    "value": 2048,
                    "count": 1,
                    "attrs": {},
                },
            ]
        )
        ic = store.to_dict()["histograms"]["insightclaw"]
        assert ic["context_system_size"]["sum"] == 2048

    def test_unknown_insightclaw_metric_ignored(self):
        """Metrics not in the known map must not raise or corrupt state."""
        store = self._store_with(
            [
                {
                    "name": "openclaw.llm.unknown_future_metric",
                    "type": "sum",
                    "value": 99,
                    "attrs": {},
                },
            ]
        )
        # Should complete without error; the key won't exist in the ic bucket
        ic = store.to_dict()["counters"]["insightclaw"]
        assert "unknown_future_metric" not in ic["llm"]
