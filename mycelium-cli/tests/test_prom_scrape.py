# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Unit tests for the minimal Prometheus text-format parser and the HTTP-RED
roll-up used by ``mycelium metrics collect`` to scrape CFN service
``/metrics`` endpoints.

Why this is worth its own test file (and not just an integration smoke
test against a live mgmt-plane container):

  * The exposition format has half a dozen edge cases (blank lines,
    HELP/TYPE comments, label-value backslash escapes, +Inf buckets,
    missing trailing newlines) that a "happy path" sample wouldn't cover.
    Each one of those has burned someone in production at least once.
  * The HTTP-RED roll-up specifically *excludes* 404 from the error count
    (health probes / scanner noise dominate it) and converts seconds →
    milliseconds (to match every other histogram panel in
    ``mycelium metrics show``). Both of those decisions are easy to
    silently regress, and both are the kind of bug that doesn't surface
    until somebody is staring at a dashboard wondering why error rate
    flipped or why latency suddenly looks 1000× off.
  * ``histogram_quantile`` mirrors Prometheus's PromQL semantics
    (linear interpolation within buckets, +Inf clamped to the previous
    finite bound). Subtle behaviours like the +Inf clamp and the
    "all observations in one bucket" edge case are exactly the kind of
    thing where a one-line refactor can silently start returning ``inf``
    or zero for a healthy p99.
"""

from __future__ import annotations

import math

from mycelium.prom_scrape import (
    Sample,
    aggregate_http_red,
    histogram_quantile,
    parse_text,
)


# ---------------------------------------------------------------------------
# parse_text — exposition-format edge cases
# ---------------------------------------------------------------------------


def test_parse_text_skips_comments_and_blanks() -> None:
    """HELP/TYPE comments and blank lines must be ignored, not parsed as samples."""
    body = """\
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter

http_requests_total 42

# trailing comment
"""
    samples = parse_text(body)
    assert len(samples) == 1
    assert samples[0].name == "http_requests_total"
    assert samples[0].value == 42.0
    assert samples[0].labels == {}


def test_parse_text_label_extraction_with_escapes() -> None:
    """Labels with quotes/backslashes must be unescaped per the Prometheus spec.

    The two escape sequences we have to honour are ``\\"`` and ``\\\\``;
    everything else (``\\n`` etc.) does not appear in any series we scrape
    and we deliberately don't unescape it (see the parser comment).
    """
    body = (
        'http_requests_total{handler="/api/v1/foo",method="GET",status="200"} 17\n'
        # An escaped quote in the label value — pathological but legal.
        r'odd_label{name="quote=\"x\""} 1' + "\n"
    )
    samples = parse_text(body)
    assert samples[0].labels == {
        "handler": "/api/v1/foo",
        "method": "GET",
        "status": "200",
    }
    assert samples[0].value == 17.0
    assert samples[1].labels == {"name": 'quote="x"'}


def test_parse_text_handles_inf_bucket_boundary() -> None:
    """``le="+Inf"`` is a normal histogram boundary; the parser stores it verbatim
    in the label, and ``aggregate_http_red`` is what filters it out of the
    min/max approximation."""
    body = (
        'http_request_duration_seconds_bucket{le="+Inf"} 100\n'
        'http_request_duration_seconds_bucket{le="0.5"} 80\n'
    )
    samples = parse_text(body)
    assert len(samples) == 2
    assert samples[0].labels["le"] == "+Inf"
    assert samples[0].value == 100.0  # bucket *count*, not boundary
    assert samples[1].labels["le"] == "0.5"
    assert samples[1].value == 80.0


def test_parse_text_drops_malformed_lines_without_crashing() -> None:
    """A garbled line must not poison the rest of the payload."""
    body = (
        "this is not a metric line at all\n"
        "http_requests_total 5\n"
        "another_garbage_line==!!\n"
    )
    samples = parse_text(body)
    assert len(samples) == 1
    assert samples[0].name == "http_requests_total"


def test_parse_text_empty_string_yields_no_samples() -> None:
    assert parse_text("") == []


# ---------------------------------------------------------------------------
# aggregate_http_red — RED roll-up of fastapi-instrumentator series
# ---------------------------------------------------------------------------


def _stock_fastapi_instrumentator_payload() -> str:
    """Minimal-but-realistic snippet from prometheus-fastapi-instrumentator.

    Two routes, three status codes (200, 404, 500), a small histogram. This
    is the shape every CFN service emits today (mgmt-plane-svc,
    knowledge-memory) so we want at least one test to assert against it
    end-to-end rather than against synthetic samples.
    """
    return """\
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{handler="/api/v1/sessions",method="POST",status="200"} 50
http_requests_total{handler="/api/v1/sessions",method="POST",status="500"} 3
http_requests_total{handler="/healthz",method="GET",status="200"} 2000
http_requests_total{handler="/healthz",method="GET",status="404"} 17
# HELP http_request_duration_seconds HTTP request duration
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{handler="/api/v1/sessions",le="0.1"} 30
http_request_duration_seconds_bucket{handler="/api/v1/sessions",le="0.5"} 50
http_request_duration_seconds_bucket{handler="/api/v1/sessions",le="2.5"} 53
http_request_duration_seconds_bucket{handler="/api/v1/sessions",le="+Inf"} 53
http_request_duration_seconds_count{handler="/api/v1/sessions"} 53
http_request_duration_seconds_sum{handler="/api/v1/sessions"} 12.4
"""


def test_aggregate_http_red_totals_and_error_filter() -> None:
    samples = parse_text(_stock_fastapi_instrumentator_payload())
    rolled = aggregate_http_red(samples)

    # Total = 50 + 3 + 2000 + 17 = 2070
    assert rolled["calls"] == 2070
    # Errors must include the 500 but exclude all 404s (health-probe noise),
    # and exclude the 200s. 50 + 2000 are 200s; 17 is 404; only the 3 × 500.
    assert rolled["errors"] == 3
    assert set(rolled["by_route"].keys()) == {"/api/v1/sessions", "/healthz"}
    sessions_route = rolled["by_route"]["/api/v1/sessions"]
    assert sessions_route["calls"] == 53
    assert sessions_route["errors"] == 3


def test_aggregate_http_red_latency_seconds_to_ms_conversion() -> None:
    """Sum field must be returned in milliseconds to match the OTLP histogram convention."""
    samples = parse_text(_stock_fastapi_instrumentator_payload())
    rolled = aggregate_http_red(samples)
    lat = rolled["by_route"]["/api/v1/sessions"]["latency_ms"]
    assert lat["count"] == 53
    # 12.4s → 12_400ms. Use approx because float arithmetic.
    assert abs(lat["sum"] - 12_400.0) < 1e-6


def test_aggregate_http_red_captures_full_bucket_array() -> None:
    """Buckets must round-trip into a sorted (le_ms, cumulative_count) list,
    with +Inf preserved as math.inf — that's what histogram_quantile expects."""
    samples = parse_text(_stock_fastapi_instrumentator_payload())
    rolled = aggregate_http_red(samples)
    buckets = rolled["by_route"]["/api/v1/sessions"]["latency_ms"]["buckets"]
    # Sorted ascending by upper bound, in milliseconds.
    bounds = [b for b, _ in buckets]
    assert bounds == sorted(bounds)
    assert bounds[0] == 100.0     # 0.1s
    assert bounds[-2] == 2500.0   # 2.5s — last finite
    assert math.isinf(bounds[-1])
    # Cumulative counts must be monotonically non-decreasing — a regression
    # here means we'd compute negative bucket populations in quantile().
    counts = [c for _, c in buckets]
    assert counts == sorted(counts)
    assert counts[-1] == 53       # +Inf bucket equals the histogram's _count


def test_aggregate_http_red_handles_no_samples() -> None:
    """A target reachable but with zero traffic must produce a clean zero-state dict."""
    rolled = aggregate_http_red([])
    assert rolled == {"calls": 0, "errors": 0, "by_route": {}}


def test_aggregate_http_red_unlabeled_handler_does_not_crash() -> None:
    """Some non-fastapi-instrumentator exporters omit the ``handler`` label."""
    samples = [
        Sample(name="http_requests_total", labels={"status": "200"}, value=7),
    ]
    rolled = aggregate_http_red(samples)
    assert rolled["calls"] == 7
    assert "<unlabeled>" in rolled["by_route"]


# ---------------------------------------------------------------------------
# histogram_quantile — Prometheus-compatible interpolation
# ---------------------------------------------------------------------------


def test_histogram_quantile_interpolates_within_bucket() -> None:
    """Median of a uniform 0–10ms population should land mid-bucket."""
    # 100 samples, all in the (5, 10] bucket — Prometheus says the p50 is
    # at the linear midpoint of that bucket: 5 + 0.5 * (10 - 5) = 7.5.
    buckets = [(5.0, 0), (10.0, 100), (math.inf, 100)]
    assert histogram_quantile(0.50, buckets) == 7.5


def test_histogram_quantile_realistic_health_check_distribution() -> None:
    """Sub-millisecond health checks (the actual /health distribution)."""
    # 1000 health checks, 990 land in (0, 1ms] and 10 in (1, 5ms].
    buckets = [(1.0, 990), (5.0, 1000), (math.inf, 1000)]
    p50 = histogram_quantile(0.50, buckets)
    p99 = histogram_quantile(0.99, buckets)
    assert p50 is not None and p50 < 1.0  # median is sub-ms — the whole point
    assert p99 is not None and 0.0 < p99 <= 5.0


def test_histogram_quantile_clamps_inf_tail_to_last_finite_bound() -> None:
    """A request slower than the largest finite bucket lands in +Inf — we
    return the previous finite bound rather than ``inf`` so the panel
    stays readable. This is the only place we deviate from a strict
    Prometheus implementation, and it's a deliberate choice (documented
    in prom_scrape.histogram_quantile)."""
    buckets = [(100.0, 50), (1000.0, 99), (math.inf, 100)]
    # p99 = 99 → falls exactly on the 1000ms bound → returns 1000ms.
    assert histogram_quantile(0.99, buckets) == 1000.0
    # p999 = 99.9 → falls in the +Inf bucket → clamp to last finite (1000).
    assert histogram_quantile(0.999, buckets) == 1000.0


def test_histogram_quantile_returns_none_on_empty_or_zero_observations() -> None:
    """No data = no estimate — the panel must show — rather than 0 or NaN."""
    assert histogram_quantile(0.50, []) is None
    assert histogram_quantile(0.50, [(1.0, 0), (math.inf, 0)]) is None


def test_histogram_quantile_rejects_out_of_range_q() -> None:
    """Caller bug guard: only 0 ≤ q ≤ 1 makes sense as a quantile."""
    buckets = [(1.0, 10), (math.inf, 10)]
    assert histogram_quantile(-0.1, buckets) is None
    assert histogram_quantile(1.5, buckets) is None


# ---------------------------------------------------------------------------
# MyceliumConfig.resolve_scrape_targets — the "no config needed" path
# ---------------------------------------------------------------------------
#
# The collector mirrors the OTLP-rx convention-over-configuration pattern
# by auto-deriving CFN scrape targets from the runtime URLs that install
# already sets. These tests pin that behaviour so a future refactor can't
# silently resurrect the "user must paste a [[metrics.scrape]] block into
# config.toml" requirement.


def _make_config(
    *,
    cfn_mgmt_url: str | None = None,
    cognition_fabric_node_url: str | None = None,
    explicit_scrape: list[dict] | None = None,
):
    """Build a MyceliumConfig for resolution tests without touching disk."""
    from mycelium.config import MyceliumConfig

    return MyceliumConfig(
        runtime={
            "cfn_mgmt_url": cfn_mgmt_url,
            "cognition_fabric_node_url": cognition_fabric_node_url,
        },
        metrics={"scrape": explicit_scrape or []},
    )


def test_resolve_scrape_targets_auto_derives_cfn_mgmt() -> None:
    """The common case: install sets cfn_mgmt_url, user touches nothing, we scrape."""
    cfg = _make_config(cfn_mgmt_url="http://localhost:9000")
    targets = cfg.resolve_scrape_targets()
    assert len(targets) == 1
    assert targets[0]["name"] == "cfn-mgmt"
    assert targets[0]["url"] == "http://localhost:9000/metrics"
    assert targets[0]["kind"] == "http_red"


def test_resolve_scrape_targets_strips_trailing_slash() -> None:
    """Don't emit double slashes — some users paste URLs with trailing /."""
    cfg = _make_config(cfn_mgmt_url="http://localhost:9000/")
    assert cfg.resolve_scrape_targets()[0]["url"] == "http://localhost:9000/metrics"


def test_resolve_scrape_targets_empty_when_no_urls_configured() -> None:
    """No runtime URLs + no explicit entries = no targets (not an error)."""
    cfg = _make_config()
    assert cfg.resolve_scrape_targets() == []


def test_resolve_scrape_targets_explicit_entry_appended() -> None:
    """A user-defined scrape target (non-CFN) is merged alongside auto-derived ones."""
    cfg = _make_config(
        cfn_mgmt_url="http://localhost:9000",
        explicit_scrape=[
            {"name": "my-service", "url": "http://localhost:7777/metrics", "kind": "http_red"}
        ],
    )
    targets = cfg.resolve_scrape_targets()
    names = {t["name"] for t in targets}
    assert names == {"cfn-mgmt", "my-service"}


def test_resolve_scrape_targets_explicit_overrides_auto_by_name() -> None:
    """Explicit entry with the auto-derived name wins (escape hatch for custom URL)."""
    cfg = _make_config(
        cfn_mgmt_url="http://localhost:9000",
        explicit_scrape=[
            # Site runs mgmt plane behind an nginx path prefix.
            {"name": "cfn-mgmt", "url": "http://internal.example/mgmt/metrics", "kind": "http_red"}
        ],
    )
    targets = cfg.resolve_scrape_targets()
    assert len(targets) == 1
    assert targets[0]["url"] == "http://internal.example/mgmt/metrics"


def test_resolve_scrape_targets_skips_cfn_node_until_it_exposes_metrics() -> None:
    """cognition-fabric-node-svc has no /metrics yet — don't emit a target that
    would always show as degraded. See the _NODE_HAS_METRICS flag in
    config.MyceliumConfig.resolve_scrape_targets; flip when the CFN change
    lands."""
    cfg = _make_config(cognition_fabric_node_url="http://localhost:9002")
    assert cfg.resolve_scrape_targets() == []
