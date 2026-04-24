#!/usr/bin/env python3
"""Analyze CFN_ROUND_TRACE JSON files written by the e2e test conftest.

The conftest hook in tests/conftest.py captures one JSON file per e2e test
(in ~/.mycelium/e2e-logs/traces/) by scraping the
/api/internal/coordination/round-traces endpoint after the test completes.
This script slices that data three ways:

  1. Per-test summary       — one line per test JSON: rounds, paths, lags
  2. Per-round breakdown    — every round in the slice, with the timing
                              decomposition (collection vs CFN /decide)
  3. Aggregate distribution — median / p95 / max for elapsed_ms,
                              collection time, decide time, per-agent
                              first_response_ms, synthesis rate

Pure stdlib.  Run as:

    python tests/analyze_round_traces.py                       # latest run
    python tests/analyze_round_traces.py --last 5              # last 5 runs
    python tests/analyze_round_traces.py --glob 'test_41_*'    # by pattern
    python tests/analyze_round_traces.py --file a.json --file b.json  # explicit set
    python tests/analyze_round_traces.py --rounds              # show every round
    python tests/analyze_round_traces.py --json                # machine-readable

Default trace dir is ``$MYCELIUM_TRACE_DIR`` or ``~/.mycelium/e2e-logs/traces``.
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
    return {
        "tests": [per_test_summary(run) for run in runs],
        "aggregate": {
            "n_rounds": len(rounds),
            "n_runs": len(runs),
            "elapsed_ms": _quantiles(elapsed),
            "collection_ms": _quantiles(collections),
            "cfn_decide_ms": _quantiles(decides),
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
