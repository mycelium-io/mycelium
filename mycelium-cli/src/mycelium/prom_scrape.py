# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Minimal Prometheus text-format parser + scraper.

We deliberately do *not* depend on ``prometheus_client`` here. The CLI ships
to leaf nodes that already pull in OTLP/protobuf for OpenClaw telemetry; we
don't want a second metrics SDK on disk just to parse a text stream.
The Prometheus exposition format is small and stable enough that ~120 lines
of stdlib code cover every case we hit in practice (counters, gauges,
histograms with ``_bucket``/``_sum``/``_count``, labelled or not).

Output shape mirrors the OTLP-aggregated dicts already in ``MetricsStore`` so
``mycelium metrics show`` panels can render scraped CFN data with the same
helpers (``_fmt_num``, ``_fmt_histogram_s``) used for OTLP histograms.

Spec we follow (just the parts we need):
    https://prometheus.io/docs/instrumenting/exposition_formats/#text-based-format
"""

from __future__ import annotations

import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# A line like:  http_requests_total{method="get",status="200"} 1027 1395066363000
# The value is required; the trailing timestamp is optional and we ignore it.
# We tolerate the relaxed Prometheus text grammar — extra whitespace, empty
# label sets, and missing trailing newline.
_LINE_RE = re.compile(
    r"""
    ^                                       # start
    (?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)      # metric name
    (?:\{(?P<labels>[^}]*)\})?              # optional label set
    \s+
    (?P<value>[^\s]+)                       # value (number or NaN/+Inf/-Inf)
    (?:\s+\d+)?                             # optional timestamp (discarded)
    \s*$
    """,
    re.VERBOSE,
)

_LABEL_RE = re.compile(
    r"""
    ([a-zA-Z_][a-zA-Z0-9_]*)            # label name
    \s*=\s*
    "((?:[^"\\]|\\.)*)"                 # quoted value, supports backslash escapes
    """,
    re.VERBOSE,
)


@dataclass
class Sample:
    """One Prometheus sample line, after parsing."""

    name: str
    labels: dict[str, str] = field(default_factory=dict)
    value: float = 0.0


def parse_text(body: str) -> list[Sample]:
    """Parse a Prometheus exposition text payload into a flat list of samples.

    Comments (``# HELP`` / ``# TYPE``) and blank lines are dropped. We don't
    surface metric type information because all the panels we render
    bucket samples by name suffix (``_bucket``/``_sum``/``_count``) anyway.
    """
    samples: list[Sample] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        try:
            value = float(m.group("value"))
        except ValueError:
            # NaN/+Inf/-Inf would parse fine; this covers genuinely malformed
            # values. Skip silently — better than crashing the collector loop.
            continue
        labels: dict[str, str] = {}
        if m.group("labels"):
            for lname, lval in _LABEL_RE.findall(m.group("labels")):
                # Undo Prometheus's two backslash escapes (\\ and \"). We
                # don't bother with \n because it doesn't appear in any label
                # we're scraping.
                labels[lname] = lval.replace(r"\\", "\\").replace(r"\"", '"')
        samples.append(Sample(name=m.group("name"), labels=labels, value=value))
    return samples


def aggregate_http_red(samples: list[Sample]) -> dict:
    """Roll up ``prometheus-fastapi-instrumentator``'s standard HTTP series.

    Returns a dict shaped like::

        {
            "calls":   <int>,         # total count of all requests
            "errors":  <int>,         # 5xx + 4xx (excluding 404 noise)
            "by_route": {
                "<handler>": {
                    "calls":  <int>,
                    "errors": <int>,
                    "latency_ms": {
                        "count":   <int>, "sum": <ms>,
                        "buckets": [(<le_ms>, <cumulative_count>), ...],
                    },
                },
                ...
            },
        }

    We capture the *full bucket array* rather than collapsing to a min/max
    pair because real percentiles (via ``histogram_quantile``) are far more
    useful than bucket-edge approximations. Buckets are stored as a list of
    ``(upper_bound_ms, cumulative_count)`` tuples sorted ascending, with
    ``+Inf`` represented as ``math.inf`` — exactly what
    ``histogram_quantile`` expects.
    """
    by_route: dict[str, dict] = {}
    total_calls = 0
    total_errors = 0
    # Buckets arrive in arbitrary order across the text payload; collect into
    # per-handler dicts first, then sort once at the end.
    bucket_dicts: dict[str, dict[float, int]] = {}

    for s in samples:
        # Total request count is in `http_requests_total` (a counter).
        if s.name == "http_requests_total":
            handler = s.labels.get("handler", "<unlabeled>")
            status = s.labels.get("status", "")
            route = by_route.setdefault(handler, _empty_route())
            route["calls"] += int(s.value)
            total_calls += int(s.value)
            # 4xx (except 404) and 5xx count as errors. 404 dominates noise
            # from health probes / scanners and is excluded.
            try:
                code = int(status)
            except ValueError:
                code = 0
            if code >= 500 or (400 <= code < 500 and code != 404):
                route["errors"] += int(s.value)
                total_errors += int(s.value)

        # Latency histogram: `http_request_duration_seconds_{bucket,sum,count}`.
        elif s.name == "http_request_duration_seconds_count":
            handler = s.labels.get("handler", "<unlabeled>")
            route = by_route.setdefault(handler, _empty_route())
            route["latency_ms"]["count"] = int(s.value)
        elif s.name == "http_request_duration_seconds_sum":
            handler = s.labels.get("handler", "<unlabeled>")
            route = by_route.setdefault(handler, _empty_route())
            # Convert from seconds to milliseconds — matches OTLP histogram
            # convention used by every other panel in `mycelium metrics show`.
            route["latency_ms"]["sum"] = s.value * 1000.0
        elif s.name == "http_request_duration_seconds_bucket":
            handler = s.labels.get("handler", "<unlabeled>")
            le = s.labels.get("le", "")
            if not le:
                continue
            if le == "+Inf":
                edge_ms = math.inf
            else:
                try:
                    edge_ms = float(le) * 1000.0
                except ValueError:
                    continue
            # Ensure the route exists; bucket-only handlers are legal but
            # unusual.
            by_route.setdefault(handler, _empty_route())
            bucket_dicts.setdefault(handler, {})[edge_ms] = int(s.value)

    # Materialize sorted bucket arrays.
    for handler, edges in bucket_dicts.items():
        sorted_buckets = sorted(edges.items(), key=lambda kv: kv[0])
        by_route[handler]["latency_ms"]["buckets"] = sorted_buckets

    return {
        "calls": total_calls,
        "errors": total_errors,
        "by_route": by_route,
    }


def histogram_quantile(q: float, buckets: list[tuple[float, float]]) -> float | None:
    """Estimate the q-th quantile (0 ≤ q ≤ 1) from cumulative histogram buckets.

    Mirrors Prometheus's ``histogram_quantile()`` PromQL function:

      * Buckets are ``(upper_bound, cumulative_count)`` pairs, sorted
        ascending, with the final bound being ``+Inf``.
      * If the target bucket has a finite upper bound, linearly interpolate
        within the bucket between the previous bound (or 0) and this bound.
      * If the target falls in the ``+Inf`` bucket, return the previous
        finite upper bound (we have no information beyond it; clamping
        avoids returning ``inf`` for a healthy p99).
      * Returns ``None`` when there's nothing to estimate from (no
        observations, or buckets list missing/empty).

    Returned units match the bucket bounds (so callers passing
    millisecond-scaled buckets get milliseconds back, no further conversion
    needed).
    """
    if not buckets or not (0.0 <= q <= 1.0):
        return None
    total = buckets[-1][1]
    if total <= 0:
        return None

    target = q * total
    prev_bound = 0.0
    prev_count = 0.0
    for bound, count in buckets:
        if count >= target:
            if math.isinf(bound):
                # Target lies in the open-ended +Inf bucket. The best
                # honest answer is "≥ the previous finite bound"; we return
                # that bound rather than +Inf so the panel doesn't print
                # nonsense for a long-tail outlier.
                return prev_bound if prev_bound > 0 else None
            span = bound - prev_bound
            in_bucket = count - prev_count
            if in_bucket <= 0:
                # No observations actually fall in this bucket — Prometheus
                # treats this as "target sits at the bucket boundary".
                return bound
            frac = (target - prev_count) / in_bucket
            return prev_bound + frac * span
        prev_bound = bound if not math.isinf(bound) else prev_bound
        prev_count = count
    return None


def _empty_route() -> dict:
    return {
        "calls": 0,
        "errors": 0,
        # ``buckets`` is a list of (upper_bound_ms, cumulative_count) tuples
        # sorted ascending, with the final entry being (math.inf, total).
        # See aggregate_http_red and histogram_quantile for usage.
        "latency_ms": {"count": 0, "sum": 0.0, "buckets": []},
    }


def scrape(url: str, timeout: float = 5.0) -> list[Sample] | None:
    """GET a Prometheus ``/metrics`` endpoint and parse it.

    Returns None on any network/HTTP/parse failure — callers should treat a
    None as "target unavailable, render nothing" rather than crashing the
    collector loop.
    """
    try:
        req = urllib.request.Request(url, method="GET", headers={
            # Stock prometheus-fastapi-instrumentator returns 0.0.4 text
            # when no Accept header is set; this is fine but being explicit
            # protects us if a target ever serves protobuf by default.
            "Accept": "text/plain; version=0.0.4",
            "User-Agent": "mycelium-metrics-collector/1",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return None
    return parse_text(body)
