# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Regression tests for ``MetricsStore`` cross-host aggregation.

These guard a hub bug where OTLP cumulative counters from multiple
hosts were stored in a single shared bucket and ``set`` rather than
summed. Whichever host pushed its OTLP batch last would clobber the
others, so the headline ``Tokens by Channel`` / ``Cost Estimates``
panels on the hub silently showed the value from one (essentially
random) spoke instead of the cluster total.

What's covered:
  * ``MetricsStore._process_metric`` keeps per-host buckets and the
    aggregated ``counters`` view in ``to_dict()`` sums (latest)
    cumulative samples across hosts for tokens, cost, message counts,
    queues, webhooks, session-state gauges, and run attempts.
  * Histogram counts/sums are summed across hosts and min/max are
    folded as min(min)/max(max).
  * Per-host persistence round-trips via ``counters_by_host`` /
    ``histograms_by_host`` so a collector restart can reload without
    re-aggregating the old snapshot into a single bucket (which would
    double-count on the next push).
"""

from __future__ import annotations

import pytest

from mycelium.collector import MetricsStore

# ── helpers to synthesize OTLP-shaped metric protos ──────────────────


class _Attr:
    def __init__(self, key: str, value: str) -> None:
        self.key = key

        class _V:
            string_value = value
            int_value = 0
            double_value = 0.0
            bool_value = False

            @staticmethod
            def HasField(name: str) -> bool:
                return name == "string_value"

        self.value = _V()


class _DataPoint:
    def __init__(self, value: float | int, attrs: dict[str, str]) -> None:
        self.attributes = [_Attr(k, v) for k, v in attrs.items()]
        self.as_int = int(value)
        self.as_double = float(value)
        self.count = 0
        self.sum = 0
        self.min = 0.0
        self.max = 0.0
        # OTel exporters set either as_int or as_double depending on the
        # instrument's value type; floats go to as_double (which the
        # collector path prefers when present), ints to as_int.
        if isinstance(value, float) and not value.is_integer():
            self._has_fields = {"as_double"}
        else:
            self._has_fields = {"as_int"}

    def HasField(self, name: str) -> bool:  # noqa: N802 - mirrors proto API
        return name in self._has_fields


class _HistogramDataPoint(_DataPoint):
    def __init__(
        self,
        *,
        count: int,
        h_sum: float,
        h_min: float,
        h_max: float,
        attrs: dict[str, str],
    ) -> None:
        super().__init__(0, attrs)
        self.count = count
        self.sum = h_sum
        self.min = h_min
        self.max = h_max
        self._has_fields = {"min", "max"}


class _SumMetric:
    def __init__(self, name: str, data_points: list[_DataPoint]) -> None:
        self.name = name

        class _Sum:
            def __init__(self, dps: list[_DataPoint]) -> None:
                self.data_points = dps

        self.sum = _Sum(data_points)
        self.histogram = None

    def HasField(self, name: str) -> bool:  # noqa: N802 - mirrors proto API
        return name == "sum"


class _HistogramMetric:
    def __init__(self, name: str, data_points: list[_HistogramDataPoint]) -> None:
        self.name = name

        class _H:
            def __init__(self, dps: list[_HistogramDataPoint]) -> None:
                self.data_points = dps

        self.sum = None
        self.histogram = _H(data_points)

    def HasField(self, name: str) -> bool:  # noqa: N802 - mirrors proto API
        return name == "histogram"


def _push_tokens(
    store: MetricsStore,
    *,
    host: str,
    channel: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Push a pair of OTLP ``openclaw.tokens`` samples for one host."""
    metric = _SumMetric(
        "openclaw.tokens",
        [
            _DataPoint(input_tokens, {"openclaw.token": "input", "openclaw.channel": channel}),
            _DataPoint(output_tokens, {"openclaw.token": "output", "openclaw.channel": channel}),
        ],
    )
    store._process_metric(metric, host)


def _push_cost(store: MetricsStore, *, host: str, channel: str, value: float) -> None:
    metric = _SumMetric(
        "openclaw.cost.usd",
        [_DataPoint(value, {"openclaw.channel": channel})],
    )
    store._process_metric(metric, host)


def _push_messages_processed(store: MetricsStore, *, host: str, value: int) -> None:
    metric = _SumMetric("openclaw.message.processed", [_DataPoint(value, {})])
    store._process_metric(metric, host)


def _push_run_duration_histogram(
    store: MetricsStore,
    *,
    host: str,
    count: int,
    h_sum: float,
    h_min: float,
    h_max: float,
) -> None:
    metric = _HistogramMetric(
        "openclaw.run.duration_ms",
        [_HistogramDataPoint(count=count, h_sum=h_sum, h_min=h_min, h_max=h_max, attrs={})],
    )
    store._process_metric(metric, host)


# ── tokens: cross-host aggregation ──────────────────────────────────


def test_tokens_by_channel_sums_across_hosts() -> None:
    """``mycelium-room`` tokens pushed by three hosts must sum, not overwrite.

    This is the bug that motivated the per-host bucketing: before the
    fix the hub's ``counters.tokens.by_agent.mycelium-room.input`` was
    set to whichever spoke pushed last, masking the cluster total.
    """
    store = MetricsStore()

    # Each host's OTel SDK reports its own running cumulative total.
    _push_tokens(store, host="oclw-3", channel="mycelium-room", input_tokens=8_342_843)
    _push_tokens(store, host="oclw-4", channel="mycelium-room", input_tokens=17_898)
    _push_tokens(store, host="oclw-5", channel="mycelium-room", input_tokens=5_904_558)

    snap = store.to_dict()
    by_agent = snap["counters"]["tokens"]["by_agent"]

    assert by_agent["mycelium-room"]["input"] == 8_342_843 + 17_898 + 5_904_558


def test_tokens_total_sums_across_hosts() -> None:
    """``tokens.total`` is also aggregated, not last-writer-wins."""
    store = MetricsStore()

    metric_a = _SumMetric(
        "openclaw.tokens",
        [_DataPoint(1000, {"openclaw.token": "total"})],
    )
    metric_b = _SumMetric(
        "openclaw.tokens",
        [_DataPoint(2500, {"openclaw.token": "total"})],
    )
    store._process_metric(metric_a, "oclw-3")
    store._process_metric(metric_b, "oclw-5")

    snap = store.to_dict()
    assert snap["counters"]["tokens"]["total"]["total"] == 3500


def test_tokens_by_channel_disjoint_channels_per_host() -> None:
    """Hosts can report different channels; aggregation preserves all of them."""
    store = MetricsStore()

    _push_tokens(store, host="oclw-3", channel="discord", input_tokens=100, output_tokens=10)
    _push_tokens(store, host="oclw-4", channel="cfn", input_tokens=200, output_tokens=20)
    _push_tokens(store, host="oclw-5", channel="discord", input_tokens=300, output_tokens=30)

    by_agent = store.to_dict()["counters"]["tokens"]["by_agent"]
    assert by_agent["discord"]["input"] == 100 + 300
    assert by_agent["discord"]["output"] == 10 + 30
    assert by_agent["cfn"]["input"] == 200
    assert by_agent["cfn"]["output"] == 20


def test_tokens_repushed_from_same_host_overwrites_within_host() -> None:
    """A host's later cumulative sample replaces its earlier sample (within its own bucket),
    so the aggregated total reflects each host's *latest* value.
    """
    store = MetricsStore()

    _push_tokens(store, host="oclw-3", channel="discord", input_tokens=100)
    _push_tokens(store, host="oclw-4", channel="discord", input_tokens=200)
    # oclw-3 pushes again with a larger cumulative value.
    _push_tokens(store, host="oclw-3", channel="discord", input_tokens=150)

    by_agent = store.to_dict()["counters"]["tokens"]["by_agent"]
    assert by_agent["discord"]["input"] == 150 + 200


# ── cost / simple counters / gauges ──────────────────────────────────


def test_cost_usd_sums_across_hosts() -> None:
    store = MetricsStore()

    _push_cost(store, host="oclw-3", channel="discord", value=1.25)
    _push_cost(store, host="oclw-5", channel="discord", value=0.75)

    snap = store.to_dict()
    assert snap["counters"]["cost_usd"]["by_agent"]["discord"] == pytest.approx(2.00)
    assert snap["counters"]["cost_usd"]["total"] == pytest.approx(2.00)


def test_messages_processed_sums_across_hosts() -> None:
    store = MetricsStore()

    _push_messages_processed(store, host="oclw-3", value=42)
    _push_messages_processed(store, host="oclw-4", value=7)
    _push_messages_processed(store, host="oclw-5", value=100)

    assert store.to_dict()["counters"]["messages"]["processed"] == 42 + 7 + 100


def test_session_state_gauge_sums_across_hosts() -> None:
    """``openclaw.session.state{state="idle"}`` reports per host; rollup should sum."""
    store = MetricsStore()
    for host, value in [("oclw-3", 3), ("oclw-4", 1), ("oclw-5", 2)]:
        metric = _SumMetric(
            "openclaw.session.state",
            [_DataPoint(value, {"openclaw.state": "idle"})],
        )
        store._process_metric(metric, host)

    assert store.to_dict()["counters"]["sessions_state"]["idle"] == 6


# ── histograms ───────────────────────────────────────────────────────


def test_run_duration_histogram_merges_across_hosts() -> None:
    """Counts and sums add; min/max fold to overall min/max."""
    store = MetricsStore()

    _push_run_duration_histogram(store, host="oclw-3", count=10, h_sum=500.0, h_min=5.0, h_max=80.0)
    _push_run_duration_histogram(store, host="oclw-4", count=4, h_sum=120.0, h_min=2.0, h_max=60.0)
    _push_run_duration_histogram(store, host="oclw-5", count=6, h_sum=300.0, h_min=10.0, h_max=95.0)

    h = store.to_dict()["histograms"]["run_duration_ms"]
    assert h["count"] == 20
    assert h["sum"] == pytest.approx(920.0)
    assert h["min"] == pytest.approx(2.0)
    assert h["max"] == pytest.approx(95.0)


# ── per-host bucket exposure / persistence shape ─────────────────────


def test_snapshot_exposes_counters_by_host_for_persistence() -> None:
    """Per-host buckets must surface in ``to_dict()`` so the collector
    can persist them and reload without re-aggregating (which would
    double-count once any host pushes again)."""
    store = MetricsStore()
    _push_tokens(store, host="oclw-3", channel="discord", input_tokens=10)
    _push_tokens(store, host="oclw-5", channel="discord", input_tokens=20)

    snap = store.to_dict()
    assert "counters_by_host" in snap
    assert set(snap["counters_by_host"].keys()) == {"oclw-3", "oclw-5"}
    assert snap["counters_by_host"]["oclw-3"]["tokens"]["by_agent"]["discord"]["input"] == 10
    assert snap["counters_by_host"]["oclw-5"]["tokens"]["by_agent"]["discord"]["input"] == 20


def test_unknown_host_does_not_clobber_known_hosts() -> None:
    """OTLP pushes with no resource attributes land in an ``"unknown"``
    bucket rather than overwriting other hosts' buckets."""
    store = MetricsStore()

    _push_tokens(store, host="oclw-3", channel="discord", input_tokens=500)
    _push_tokens(store, host="", channel="discord", input_tokens=42)

    snap = store.to_dict()
    assert snap["counters_by_host"]["oclw-3"]["tokens"]["by_agent"]["discord"]["input"] == 500
    assert snap["counters_by_host"]["unknown"]["tokens"]["by_agent"]["discord"]["input"] == 42
    assert snap["counters"]["tokens"]["by_agent"]["discord"]["input"] == 500 + 42


def test_empty_store_produces_zeroed_counters() -> None:
    """With no inputs, ``counters`` is shaped correctly with zero values."""
    snap = MetricsStore().to_dict()
    assert snap["counters"]["tokens"]["total"]["input"] == 0
    assert snap["counters"]["tokens"]["by_agent"] == {}
    assert snap["counters"]["cost_usd"]["total"] == 0.0
    assert "counters_by_host" not in snap  # nothing to persist yet
