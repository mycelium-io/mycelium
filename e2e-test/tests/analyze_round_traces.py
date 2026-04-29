#!/usr/bin/env python3
"""Analyze CFN_ROUND_TRACE JSON files written by the e2e test conftest.

The conftest hook in tests/conftest.py captures one JSON file per e2e test
(in ~/.mycelium/e2e-logs/traces/) by scraping the
/api/internal/coordination/round-traces endpoint after the test completes.
This script slices that data four ways:

  1. Per-test summary       — one line per test JSON: rounds, paths, lags
  2. Per-round breakdown    — every round in the slice, with the timing
                              decomposition (collection vs CFN /decide)
  3. Aggregate distribution — median / p95 / max for elapsed_ms,
                              collection time, decide time, per-agent
                              first_response_ms, synthesis rate
  4. CFN timing envelope    — per-stage distributions from
                              ``cfn_internal_timing`` (Sites 1–6: wire,
                              middleware, deps, route, thread wait,
                              in-thread, post-thread resume, pipeline,
                              loop lag) plus ``cfn_call_timing`` (httpx
                              wall, json parse, loop lag headers). This
                              is what the per-fix smoke runs (PR E v1
                              through v4-B + KXP profiling) consumed
                              ad-hoc; promoted here so the same
                              attribution can be reproduced from any
                              future trace dir without one-off scripts.

Pure stdlib.  Run as:

    python tests/analyze_round_traces.py                       # latest run
    python tests/analyze_round_traces.py --last 5              # last 5 runs
    python tests/analyze_round_traces.py --glob 'test_41_*'    # by pattern
    python tests/analyze_round_traces.py --file a.json --file b.json  # explicit set
    python tests/analyze_round_traces.py --rounds              # show every round
    python tests/analyze_round_traces.py --wedges              # attribute long rounds (A/B/C/D)
    python tests/analyze_round_traces.py --compare-dir DIR     # diff timing vs DIR
    python tests/analyze_round_traces.py --json                # machine-readable

Default trace dir is ``$MYCELIUM_TRACE_DIR`` or ``~/.mycelium/e2e-logs/traces``.

Wedge attribution patterns (see cfn_decide_investigation_history.md):

  A — pure event-loop wedge inside CFN
      post_thread_resume_ms dominates; thread did its work but the
      awaiting coroutine couldn't resume. Suspects: litellm async hooks,
      sync AgensGraph calls, GIL contention from acompletion-on-Bedrock.
  B — uvicorn accept-queue backup
      wire_to_middleware_ms dominates; the worker was busy when the
      request arrived. Almost always downstream of A.
  C — thread pool starvation
      thread_wait_ms dominates; default executor was saturated. The
      original PR E v1 fix (bump CFN_DEFAULT_EXECUTOR_WORKERS) targets
      this. Should be near-zero on any post-v1 trace.
  D — real work
      in_thread_ms dominates; the engines pipeline actually was the slow
      thing. Rare and informative when it happens.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TRACE_DIR = Path(
    os.environ.get("MYCELIUM_TRACE_DIR", str(Path.home() / ".mycelium" / "e2e-logs" / "traces"))
)


@dataclass
class TestRun:
    """One captured test run (one JSON file from the conftest hook)."""

    path: Path
    test_name: str
    outcome: str  # "passed" | "failed" | "error" | "unknown"
    rounds: list[dict]

    @classmethod
    def load(cls, path: Path) -> TestRun:
        data = json.loads(path.read_text())
        # Filename format: <test_name>_<YYYYMMDD>_<HHMMSS>_<outcome>.json
        stem = path.stem
        parts = stem.rsplit("_", 1)
        outcome = parts[1] if len(parts) == 2 else "unknown"
        # Strip the timestamp (last two underscored segments before outcome).
        name_parts = parts[0].rsplit("_", 2)
        test_name = name_parts[0] if len(name_parts) >= 3 else parts[0]
        return cls(
            path=path,
            test_name=test_name,
            outcome=outcome,
            rounds=data.get("traces", []),
        )


def _quantiles(values: list[float]) -> dict[str, float | None]:
    """Return {min, median, mean, p75, p95, max}; None entries when empty."""
    if not values:
        return {"min": None, "median": None, "mean": None, "p75": None, "p95": None, "max": None}
    s = sorted(values)
    n = len(s)
    return {
        "min": s[0],
        "median": statistics.median(s),
        "mean": statistics.mean(s),
        "p75": s[int(n * 0.75)] if n >= 4 else s[-1],
        "p95": s[int(n * 0.95)] if n >= 5 else s[-1],
        "max": s[-1],
    }


def _fmt_ms(v: float | int | None, width: int = 8) -> str:
    """Right-align a millisecond value in ``width`` chars (or '-' if None)."""
    if v is None:
        return f"{'-':>{width}}"
    return f"{v:>{width}.0f}"


def discover_files(
    trace_dir: Path,
    files: list[Path] | None,
    glob: str | None,
    last: int | None,
) -> list[Path]:
    """Resolve the file selection arguments to a list of paths, newest-last."""
    if files:
        # Preserve caller-supplied order; that's how the conftest passes
        # session-captured files chronologically.
        return [Path(f) for f in files]
    pattern = glob if glob else "*.json"
    candidates = sorted(trace_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return []
    if last is not None:
        candidates = candidates[-last:]
    return candidates


def round_decomposition(rnd: dict) -> tuple[float | None, float | None]:
    """(collection_ms, decide_ms) using the new fields when present, else
    falling back to derived values from ``per_agent.first_response_ms``."""
    collection = rnd.get("last_reply_received_ms")
    if collection is None:
        per_agent = rnd.get("per_agent", {}) or {}
        frts = [a.get("first_response_ms") for a in per_agent.values()]
        frts = [v for v in frts if v is not None]
        collection = max(frts) if frts else None
    decide = rnd.get("cfn_decide_ms")
    if decide is None and rnd.get("elapsed_ms") is not None and collection is not None:
        decide = max(0.0, rnd["elapsed_ms"] - collection)
    return collection, decide


def per_test_summary(run: TestRun) -> dict[str, Any]:
    paths: dict[str, int] = {}
    synth = 0
    elapsed = []
    for r in run.rounds:
        paths[r["decision_path"]] = paths.get(r["decision_path"], 0) + 1
        for a in (r.get("per_agent") or {}).values():
            if a.get("was_synthesised"):
                synth += 1
        if r.get("elapsed_ms") is not None:
            elapsed.append(r["elapsed_ms"])
    return {
        "test": run.test_name,
        "outcome": run.outcome,
        "rounds": len(run.rounds),
        "decision_paths": paths,
        "synthesised_replies": synth,
        "longest_round_ms": max(elapsed) if elapsed else None,
        "median_round_ms": statistics.median(elapsed) if elapsed else None,
    }


def print_per_test_table(runs: list[TestRun]) -> None:
    print("=" * 100)
    print("PER-TEST SUMMARY")
    print("=" * 100)
    hdr = (
        f"{'#':<4}{'test':<40}{'outcome':<10}{'rounds':<8}"
        f"{'all_repl':<10}{'watchdog':<10}{'synth':<7}{'med_ms':<8}{'max_ms':<8}"
    )
    print(hdr)
    print("-" * 100)
    for i, run in enumerate(runs, 1):
        s = per_test_summary(run)
        paths = s["decision_paths"]
        print(
            f"{i:<4}{run.test_name[:39]:<40}{s['outcome']:<10}{s['rounds']:<8}"
            f"{paths.get('all_replied', 0):<10}{paths.get('watchdog_fired', 0):<10}"
            f"{s['synthesised_replies']:<7}"
            f"{int(s['median_round_ms']) if s['median_round_ms'] is not None else 0:<8}"
            f"{int(s['longest_round_ms']) if s['longest_round_ms'] is not None else 0:<8}"
        )


def print_per_round_table(runs: list[TestRun]) -> None:
    print()
    print("=" * 100)
    print("PER-ROUND BREAKDOWN  (collection = last_reply_received_ms; decide = cfn_decide_ms)")
    print("=" * 100)
    hdr = (
        f"{'run':<4}{'r':<3}{'path':<14}{'outcome':<10}"
        f"{'elapsed':>10}{'collect':>10}{'decide':>10}"
        f"{'msgs':>5}{'resp_kb':>8}  agents (first_response_ms)"
    )
    print(hdr)
    print("-" * 125)
    for i, run in enumerate(runs, 1):
        for r in run.rounds:
            collection, decide = round_decomposition(r)
            per_agent = r.get("per_agent") or {}
            agents_str = ", ".join(
                f"{h}="
                + (f"{int(a['first_response_ms'])}" if a.get("first_response_ms") is not None else "-")
                + ("*" if a.get("was_synthesised") else "")
                for h, a in per_agent.items()
            )
            msgs = r.get("cfn_messages_count")
            resp_b = r.get("cfn_response_bytes")
            print(
                f"{i:<4}{r['round_n']:<3}{r['decision_path']:<14}{(r.get('outcome') or '-'):<10}"
                f"{_fmt_ms(r.get('elapsed_ms'), 10)}{_fmt_ms(collection, 10)}{_fmt_ms(decide, 10)}"
                f"{(str(msgs) if msgs is not None else '-'):>5}"
                f"{(f'{resp_b/1024:.1f}' if resp_b is not None else '-'):>8}"
                f"  {agents_str}"
            )
    print()
    print("  '*' after an agent timing means the reply was synthesised (timed out)")
    print("  msgs = mediator messages CFN returned;  resp_kb = CFN response size")


def print_aggregate(runs: list[TestRun]) -> None:
    rounds = [r for run in runs for r in run.rounds]
    n = len(rounds)
    print()
    print("=" * 100)
    print(f"AGGREGATE DISTRIBUTION  (n={n} rounds across {len(runs)} test runs)")
    print("=" * 100)
    if not rounds:
        print("  (no rounds)")
        return

    paths: dict[str, int] = {}
    for r in rounds:
        paths[r["decision_path"]] = paths.get(r["decision_path"], 0) + 1
    print("\nDecision-path mix:")
    for p, c in sorted(paths.items(), key=lambda x: -x[1]):
        print(f"  {p:<20}{c:>5}  ({100 * c / n:5.1f}%)")

    elapsed = [r["elapsed_ms"] for r in rounds if r.get("elapsed_ms") is not None]
    collections, decides = [], []
    for r in rounds:
        c, d = round_decomposition(r)
        if c is not None:
            collections.append(c)
        if d is not None:
            decides.append(d)

    def line(label: str, values: list[float]) -> None:
        q = _quantiles(values)
        if q["median"] is None:
            print(f"  {label:<32}(no samples)")
            return
        print(
            f"  {label:<32}n={len(values):<4} "
            f"min={q['min']:>6.0f}  med={q['median']:>6.0f}  "
            f"mean={q['mean']:>6.0f}  p75={q['p75']:>6.0f}  "
            f"p95={q['p95']:>6.0f}  max={q['max']:>6.0f}"
        )

    print("\nRound timing (ms):")
    line("elapsed_ms (full round)", elapsed)
    line("collection (agents reply)", collections)
    line("decide (CFN /decide)", decides)

    # CFN response shape — what kept /decide busy when it was slow.
    msg_counts = [r["cfn_messages_count"] for r in rounds if r.get("cfn_messages_count") is not None]
    resp_bytes = [r["cfn_response_bytes"] for r in rounds if r.get("cfn_response_bytes") is not None]
    cfn_status_mix: dict[str, int] = {}
    for r in rounds:
        s = r.get("cfn_status")
        if s:
            cfn_status_mix[s] = cfn_status_mix.get(s, 0) + 1
    if msg_counts or resp_bytes or cfn_status_mix:
        print("\nCFN response shape:")
        if cfn_status_mix:
            mix = ", ".join(f"{s}={c}" for s, c in sorted(cfn_status_mix.items(), key=lambda x: -x[1]))
            print(f"  cfn_status mix                  {mix}")
        if msg_counts:
            line("cfn_messages_count (ongoing)", [float(x) for x in msg_counts])
        if resp_bytes:
            line("cfn_response_kb", [x / 1024.0 for x in resp_bytes])

    frts: list[float] = []
    synthesised = 0
    total_slots = 0
    by_handle: dict[str, list[float]] = {}
    by_handle_synth: dict[str, int] = {}
    for r in rounds:
        for handle, a in (r.get("per_agent") or {}).items():
            total_slots += 1
            v = a.get("first_response_ms")
            if v is not None:
                frts.append(v)
                by_handle.setdefault(handle, []).append(v)
            if a.get("was_synthesised"):
                synthesised += 1
                by_handle_synth[handle] = by_handle_synth.get(handle, 0) + 1

    print("\nPer-agent first_response_ms (across all agent slots):")
    line("all agents combined", frts)
    if by_handle:
        print("\n  by handle:")
        for h in sorted(by_handle):
            line(f"    {h}", by_handle[h])

    if total_slots:
        print(f"\nSynthesis rate: {synthesised}/{total_slots} agent-rounds "
              f"({100 * synthesised / total_slots:.1f}%)")
        if by_handle_synth:
            for h, c in sorted(by_handle_synth.items(), key=lambda x: -x[1]):
                print(f"  {h:<20}{c} synthesised replies")

    long_rounds = [r for r in rounds if (r.get("elapsed_ms") or 0) > 10000]
    if long_rounds:
        print(f"\nLong rounds (>10s elapsed):  {len(long_rounds)}/{n}")
        print(
            f"  {'#':<4}{'r':<3}{'elapsed':>10}{'collect':>10}{'decide':>10}"
            f"{'msgs':>5}{'resp_kb':>8}  dominant  cfn_status"
        )
        for j, r in enumerate(long_rounds, 1):
            c, d = round_decomposition(r)
            dominant = (
                "decide" if d is not None and c is not None and d > c
                else "agents" if c is not None and d is not None
                else "?"
            )
            msgs = r.get("cfn_messages_count")
            resp_b = r.get("cfn_response_bytes")
            print(
                f"  {j:<4}{r['round_n']:<3}{_fmt_ms(r.get('elapsed_ms'), 10)}"
                f"{_fmt_ms(c, 10)}{_fmt_ms(d, 10)}"
                f"{(str(msgs) if msgs is not None else '-'):>5}"
                f"{(f'{resp_b/1024:.1f}' if resp_b is not None else '-'):>8}"
                f"  {dominant:<8}  {r.get('cfn_status') or '-'}"
            )


# ---------------------------------------------------------------------------
# CFN timing envelope (cfn_internal_timing + cfn_call_timing)
#
# These are the fields the per-fix smoke runs (PR E v1..v4-B, KXP profile)
# kept reaching for ad-hoc. Promoted here so the attribution is reproducible.
# ---------------------------------------------------------------------------

# Order matters: this is the order we print the distributions in, and it
# follows the request lifecycle (outside-in) — the same order the
# investigation history walked the sites in.
INTERNAL_TIMING_FIELDS: tuple[str, ...] = (
    "wire_to_middleware_ms",          # Site 5 — Mycelium send -> CFN middleware
    "check_workspace_and_mas_ms",     # Site 3 — workspace/MAS dependency
    "vector_cache_layer_ms",          # Site 3 — vector cache dep
    "rag_cache_layer_ms",             # Site 3 — RAG cache dep
    "route_handler_ms",               # Site 3 — total route handler body
    "thread_wait_ms",                 # Site 2 — queued in default executor
    "in_thread_ms",                   # Site 2 — actual execute() runtime
    "post_thread_resume_ms",          # Site 2 — thread done -> coroutine resume
    "pipeline_ms",                    # Site 1 — pipeline.async_execute total
    "pipeline_plus_persist_setup_ms", # Site 1 — pipeline + ingest hand-off
    "to_dict_ms",                     # Site 1 — response serialisation
)

CALL_TIMING_FIELDS: tuple[str, ...] = (
    "http_ms",                        # httpx client.post wall time
    "client_setup_ms",
    "client_close_ms",
    "raise_for_status_ms",
    "json_parse_ms",
    "decide_call_total_ms",
    # Loop-lag samples folded into response headers by Site 6.
    "cfn_loop_lag_p95_ms",
    "cfn_loop_lag_mean_ms",
    "cfn_loop_lag_samples_n",
)


def _collect_timing_field(rounds: list[dict], envelope: str, field: str) -> list[float]:
    """Pull a numeric field out of `cfn_internal_timing` or `cfn_call_timing`.

    Skips rounds where the envelope is missing or the field is None — both
    happen for rounds that timed out before CFN could emit timing data.
    """
    out: list[float] = []
    for r in rounds:
        env = r.get(envelope) or {}
        v = env.get(field)
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def print_cfn_timing_envelope(runs: list[TestRun]) -> None:
    """Render distributions for every CFN-side timing field present in the data."""
    rounds = [r for run in runs for r in run.rounds]
    n = len(rounds)
    if not rounds:
        return

    rounds_with_internal = sum(1 for r in rounds if r.get("cfn_internal_timing"))
    rounds_with_call = sum(1 for r in rounds if r.get("cfn_call_timing"))
    if rounds_with_internal == 0 and rounds_with_call == 0:
        return

    print()
    print("=" * 100)
    print(
        f"CFN TIMING ENVELOPE  "
        f"(internal={rounds_with_internal}/{n} rounds, call={rounds_with_call}/{n} rounds)"
    )
    print("=" * 100)
    print(
        "  Sites correspond to cfn_decide_investigation_history.md:\n"
        "    Site 1 = pipeline / to_dict        Site 2 = thread wait / in / post\n"
        "    Site 3 = FastAPI deps / route      Site 5 = Mycelium->CFN wire\n"
        "    Site 6 = loop-lag sampler (per-request headers, see cfn_loop_lag_*)"
    )

    def block(envelope: str, fields: tuple[str, ...], header: str) -> None:
        present = [(f, _collect_timing_field(rounds, envelope, f)) for f in fields]
        present = [(f, vs) for f, vs in present if vs]
        if not present:
            return
        print(f"\n  {header}:")
        for f, vs in present:
            q = _quantiles(vs)
            print(
                f"    {f:<32}n={len(vs):<4} "
                f"min={q['min']:>6.0f}  med={q['median']:>6.0f}  "
                f"mean={q['mean']:>6.0f}  p75={q['p75']:>6.0f}  "
                f"p95={q['p95']:>6.0f}  max={q['max']:>6.0f}"
            )

    block("cfn_internal_timing", INTERNAL_TIMING_FIELDS, "cfn_internal_timing (CFN-side)")
    block("cfn_call_timing", CALL_TIMING_FIELDS, "cfn_call_timing (Mycelium-side)")


# ---------------------------------------------------------------------------
# Wedge attribution
# ---------------------------------------------------------------------------

WEDGE_THRESHOLD_MS = 10_000  # same threshold the existing "long rounds" block uses

# Each pattern names the timing field it indicts and a short label.
WEDGE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("A", "post_thread_resume_ms", "loop-wedge"),
    ("B", "wire_to_middleware_ms", "accept-queue"),
    ("C", "thread_wait_ms",        "pool-starve"),
    ("D", "in_thread_ms",          "real-work"),
)


def _classify_wedge(rnd: dict) -> tuple[str, str, float] | None:
    """Return (pattern_id, label, value_ms) for the dominant wedger, or None.

    "Dominant" = whichever of the four named fields is largest *and* exceeds
    WEDGE_THRESHOLD_MS / 4. Ties are broken by pattern order (A > B > C > D),
    which matches the investigation's own naming.
    """
    env = rnd.get("cfn_internal_timing") or {}
    candidates: list[tuple[str, str, float]] = []
    for pid, field, label in WEDGE_PATTERNS:
        v = env.get(field)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv >= WEDGE_THRESHOLD_MS / 4:
            candidates.append((pid, label, fv))
    if not candidates:
        return None
    # Largest first; ties broken by pattern order in WEDGE_PATTERNS.
    candidates.sort(key=lambda c: (-c[2], [p[0] for p in WEDGE_PATTERNS].index(c[0])))
    return candidates[0]


def print_wedge_attribution(runs: list[TestRun]) -> None:
    """For every long round, name the dominant wedger using the timing envelope."""
    rounds = [r for run in runs for r in run.rounds]
    long_rounds = [(i, r) for i, run in enumerate(runs, 1) for r in run.rounds
                   if (r.get("elapsed_ms") or 0) > WEDGE_THRESHOLD_MS]
    if not long_rounds:
        return

    print()
    print("=" * 100)
    print(f"WEDGE ATTRIBUTION  ({len(long_rounds)} rounds > {WEDGE_THRESHOLD_MS/1000:.0f}s)")
    print("=" * 100)
    print(
        "  A=loop-wedge (post_thread_resume_ms)  "
        "B=accept-queue (wire_to_middleware_ms)\n"
        "  C=pool-starve (thread_wait_ms)        "
        "D=real-work (in_thread_ms)\n"
        "  ?=no cfn_internal_timing envelope (almost always a watchdog timeout)"
    )

    counts: dict[str, int] = {}
    print(
        f"\n  {'#':<4}{'r':<3}{'elapsed':>10}  {'pattern':<14}{'attributed_ms':>14}"
        f"  {'cfn_status':<10}{'test':<40}"
    )
    print("  " + "-" * 95)
    for j, (run_idx, r) in enumerate(long_rounds, 1):
        run = runs[run_idx - 1]
        cls = _classify_wedge(r)
        if cls is None:
            pattern_label = "?-no-envelope"
            attrib_ms: float | str = "-"
            counts["?"] = counts.get("?", 0) + 1
        else:
            pid, label, ms = cls
            pattern_label = f"{pid}-{label}"
            attrib_ms = f"{ms:.0f}"
            counts[pid] = counts.get(pid, 0) + 1
        print(
            f"  {j:<4}{r.get('round_n', '?'):<3}{_fmt_ms(r.get('elapsed_ms'), 10)}  "
            f"{pattern_label:<14}{attrib_ms:>14}  "
            f"{(r.get('cfn_status') or '-'):<10}{run.test_name[:39]:<40}"
        )

    print("\n  Pattern mix:")
    for pid in [p[0] for p in WEDGE_PATTERNS] + ["?"]:
        c = counts.get(pid, 0)
        if c:
            print(f"    {pid}: {c:>3}  ({100 * c / len(long_rounds):5.1f}%)")


# ---------------------------------------------------------------------------
# Comparison across two trace directories (e.g. pre-fix vs post-fix smoke).
# ---------------------------------------------------------------------------

def _envelope_quantiles(runs: list[TestRun]) -> dict[str, dict[str, dict[str, float | None]]]:
    rounds = [r for run in runs for r in run.rounds]
    out: dict[str, dict[str, dict[str, float | None]]] = {
        "cfn_internal_timing": {},
        "cfn_call_timing": {},
    }
    for envelope, fields in (
        ("cfn_internal_timing", INTERNAL_TIMING_FIELDS),
        ("cfn_call_timing", CALL_TIMING_FIELDS),
    ):
        for f in fields:
            vs = _collect_timing_field(rounds, envelope, f)
            if vs:
                out[envelope][f] = _quantiles(vs)
    # Also include the outer round timings.
    elapsed = [r["elapsed_ms"] for r in rounds if r.get("elapsed_ms") is not None]
    out["round"] = {"elapsed_ms": _quantiles(elapsed)}  # type: ignore[assignment]
    decides = []
    for r in rounds:
        _c, d = round_decomposition(r)
        if d is not None:
            decides.append(d)
    out["round"]["cfn_decide_ms"] = _quantiles(decides)
    return out


def print_comparison(label_a: str, runs_a: list[TestRun],
                     label_b: str, runs_b: list[TestRun]) -> None:
    """Side-by-side median/p95/max diff for every timing field present in both."""
    qa = _envelope_quantiles(runs_a)
    qb = _envelope_quantiles(runs_b)
    n_a = sum(len(r.rounds) for r in runs_a)
    n_b = sum(len(r.rounds) for r in runs_b)

    print()
    print("=" * 100)
    print(f"COMPARISON  {label_a} (n={n_a}) vs {label_b} (n={n_b})")
    print("=" * 100)

    def fmt(v: float | None) -> str:
        return f"{v:>8.0f}" if v is not None else f"{'-':>8}"

    def ratio(a: float | None, b: float | None) -> str:
        if a is None or b is None or b == 0:
            return f"{'-':>8}"
        r = a / b
        if r < 1:
            return f"{1/r:>6.1f}x↓"
        return f"{r:>6.1f}x↑"

    for envelope in ("round", "cfn_internal_timing", "cfn_call_timing"):
        fields = sorted(set(qa.get(envelope, {}).keys()) | set(qb.get(envelope, {}).keys()))
        if not fields:
            continue
        print(f"\n  {envelope}:")
        print(
            f"    {'field':<32}"
            f"{'A med':>10}{'B med':>10}{'med Δ':>10}  "
            f"{'A p95':>10}{'B p95':>10}{'p95 Δ':>10}  "
            f"{'A max':>10}{'B max':>10}"
        )
        for f in fields:
            a = qa.get(envelope, {}).get(f, {})
            b = qb.get(envelope, {}).get(f, {})
            print(
                f"    {f:<32}"
                f"{fmt(a.get('median'))} {fmt(b.get('median'))} {ratio(a.get('median'), b.get('median'))}  "
                f"{fmt(a.get('p95'))} {fmt(b.get('p95'))} {ratio(a.get('p95'), b.get('p95'))}  "
                f"{fmt(a.get('max'))} {fmt(b.get('max'))}"
            )
    print("\n  Δ shows direction (B vs A): '↓' = B is faster, '↑' = B is slower.")


def to_json_report(runs: list[TestRun]) -> dict[str, Any]:
    rounds = [r for run in runs for r in run.rounds]
    elapsed = [r["elapsed_ms"] for r in rounds if r.get("elapsed_ms") is not None]
    collections, decides = [], []
    for r in rounds:
        c, d = round_decomposition(r)
        if c is not None:
            collections.append(c)
        if d is not None:
            decides.append(d)
    wedge_counts: dict[str, int] = {}
    for r in rounds:
        if (r.get("elapsed_ms") or 0) <= WEDGE_THRESHOLD_MS:
            continue
        cls = _classify_wedge(r)
        key = cls[0] if cls else "?"
        wedge_counts[key] = wedge_counts.get(key, 0) + 1
    return {
        "tests": [per_test_summary(run) for run in runs],
        "aggregate": {
            "n_rounds": len(rounds),
            "n_runs": len(runs),
            "elapsed_ms": _quantiles(elapsed),
            "collection_ms": _quantiles(collections),
            "cfn_decide_ms": _quantiles(decides),
            "cfn_internal_timing": {
                f: _quantiles(_collect_timing_field(rounds, "cfn_internal_timing", f))
                for f in INTERNAL_TIMING_FIELDS
                if _collect_timing_field(rounds, "cfn_internal_timing", f)
            },
            "cfn_call_timing": {
                f: _quantiles(_collect_timing_field(rounds, "cfn_call_timing", f))
                for f in CALL_TIMING_FIELDS
                if _collect_timing_field(rounds, "cfn_call_timing", f)
            },
            "wedge_attribution": wedge_counts,
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    p.add_argument("--dir", type=Path, default=DEFAULT_TRACE_DIR,
                   help="Trace directory (default: ~/.mycelium/e2e-logs/traces)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--file", type=Path, action="append", default=[],
                     help="Analyze a specific JSON file (repeatable)")
    src.add_argument("--glob", type=str, help="Glob pattern within --dir (e.g. 'test_41_*.json')")
    p.add_argument("--last", type=int, default=None,
                   help="Take only the most-recent N files after globbing (default: 1 if no glob/file, all otherwise)")
    p.add_argument("--rounds", action="store_true",
                   help="Print per-round breakdown table (verbose)")
    p.add_argument("--wedges", action="store_true",
                   help="Attribute every >10s round to wedge pattern A/B/C/D")
    p.add_argument("--no-envelope", action="store_true",
                   help="Suppress the CFN timing-envelope block (printed by default when present)")
    p.add_argument("--compare-dir", type=Path, default=None,
                   help="Diff timing distributions vs traces in this other directory")
    p.add_argument("--json", action="store_true",
                   help="Emit machine-readable JSON instead of pretty tables")
    args = p.parse_args(argv)

    last = args.last
    if last is None and not args.file and args.glob is None:
        last = 1  # default: just the most recent

    files = discover_files(args.dir, args.file, args.glob, last)
    if not files:
        print(f"no trace files found in {args.dir}"
              + (f" matching {args.glob!r}" if args.glob else ""), file=sys.stderr)
        return 1

    runs = [TestRun.load(f) for f in files]

    if args.json:
        json.dump(to_json_report(runs), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

    print(f"Loaded {len(runs)} test run(s) from {args.dir}")
    print_per_test_table(runs)
    if args.rounds:
        print_per_round_table(runs)
    print_aggregate(runs)
    if not args.no_envelope:
        print_cfn_timing_envelope(runs)
    if args.wedges:
        print_wedge_attribution(runs)
    if args.compare_dir is not None:
        other_files = discover_files(args.compare_dir, [], None, None)
        if not other_files:
            print(f"\n(--compare-dir: no traces in {args.compare_dir})", file=sys.stderr)
        else:
            other_runs = [TestRun.load(f) for f in other_files]
            print_comparison(str(args.dir), runs, str(args.compare_dir), other_runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
