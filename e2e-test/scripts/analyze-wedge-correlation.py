#!/usr/bin/env python3
"""Correlate openclaw scheduler queue state with e2e test boundaries.

Reads:
  1. An e2e_run_*.log produced by the test bundle (for SECTION N boundaries).
  2. journalctl --user -u openclaw-gateway.service (for dispatch timing and
     periodic [diagnostic] liveness warning lines).

Produces a per-test summary table to disambiguate three hypotheses about why
the openclaw mycelium-room scheduler wedge concentrates in distributed
(40-series) tests:

  H1 SOLO-AGENT DISPATCH PATTERN
     Single local agent receiving all local ticks, with no co-agents on the
     same gateway to naturally serialize fire-and-forget dispatchToAgent
     calls. Predicts: distributed tests show shorter tick gaps and growing
     q while matrix tests do not.

  H2 CUMULATIVE LOAD
     Wedge probability tracks total accumulated dispatches, not test type.
     Predicts: q grows monotonically across the run regardless of tier;
     distributed tests just happen to come after matrix.

  H3 CROSS-DEVICE TICK BURSTINESS
     CFN watchdog / catch-up logic for slow remote agents causes bursty
     local dispatches. Predicts: distributed tests show short tick gaps
     correlated with remote-agent latency spikes.

Usage
-----
    ./scripts/analyze-wedge-correlation.py [E2E_LOG_PATH]

If E2E_LOG_PATH is omitted, the most recent e2e_run_*.log under
~/.mycelium/e2e-logs/ is used. Read-only; safe to run against an in-flight
pytest session.
"""

from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─── Parsing ─────────────────────────────────────────────────────────────────

E2E_SECTION_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| INFO\s+\| "
    r"SECTION (?P<num>\d+): (?P<title>.+)$"
)
E2E_TS_FMT = "%Y-%m-%d %H:%M:%S"

# Journal lines (output via `-o cat`) carry the node's own ISO timestamp prefix.
JOURNAL_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})")
DISPATCH_RE = re.compile(r"\[mycelium-room\] → dispatching to (?P<agent>[\w-]+)")
LIVENESS_QUEUED_RE = re.compile(r"\bqueued=(\d+)\b")
LIVENESS_ACTIVE_RE = re.compile(r"\bactive=(\d+)\b")
# Per-agent work tuples in the liveness "work=[...]" section.
WORK_AGENT_RE = re.compile(
    r"agent:(?P<agent>[\w-]+):mycelium-room:[^\(]+\([^,]+,q=(?P<q>\d+),age=(?P<age>\d+)s"
)


def _parse_iso(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str)


def _parse_naive(ts_str: str) -> datetime:
    """E2E log timestamps are local-naive; treat as UTC (matches journal TZ)."""
    return datetime.strptime(ts_str, E2E_TS_FMT).replace(tzinfo=timezone.utc)


# ─── Data shapes ─────────────────────────────────────────────────────────────

@dataclass
class TestWindow:
    num: int
    title: str
    start: datetime
    end: Optional[datetime] = None  # filled when the next SECTION is seen


@dataclass
class TestStats:
    window: TestWindow
    dispatch_ts: list[datetime] = field(default_factory=list)
    max_q: int = 0
    max_age: int = 0
    wedge_seen: bool = False  # q >= 2 AND age >= 60s observed within the window

    @property
    def tier(self) -> str:
        if 30 <= self.window.num <= 39:
            return "matrix"
        if 40 <= self.window.num <= 49:
            return "distributed"
        return "other"

    @property
    def gaps_s(self) -> list[float]:
        return [
            (b - a).total_seconds()
            for a, b in zip(self.dispatch_ts, self.dispatch_ts[1:])
        ]


# ─── Builders ────────────────────────────────────────────────────────────────

def parse_test_windows(e2e_log: Path) -> list[TestWindow]:
    windows: list[TestWindow] = []
    with e2e_log.open() as f:
        for line in f:
            m = E2E_SECTION_RE.search(line)
            if not m:
                continue
            ts = _parse_naive(m.group("ts"))
            windows.append(TestWindow(int(m.group("num")), m.group("title").strip(), ts))
    for a, b in zip(windows, windows[1:]):
        a.end = b.start
    return windows


def fetch_journal(since: datetime) -> list[str]:
    """Pull oclw4 openclaw journal from `since` onwards. -o cat strips the
    journal's own prefix so we can rely on the node's embedded ISO timestamp,
    which has subsecond precision."""
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")
    result = subprocess.run(
        ["journalctl", "--user", "-u", "openclaw-gateway.service",
         "--since", since_str, "-o", "cat", "--no-pager"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.splitlines()


def attribute_journal(
    lines: list[str],
    windows: list[TestWindow],
    agent: str = "agent-alpha",
) -> dict[int, TestStats]:
    stats = {w.num: TestStats(window=w) for w in windows}
    # Build an index for O(log n) window lookup; small N so linear scan is fine.
    def find_window(ts: datetime) -> Optional[TestStats]:
        for s in stats.values():
            if s.window.start <= ts and (s.window.end is None or ts < s.window.end):
                return s
        return None

    for line in lines:
        tsm = JOURNAL_TS_RE.match(line)
        if not tsm:
            continue
        try:
            ts = _parse_iso(tsm.group("ts"))
        except ValueError:
            continue
        ts_utc = ts.astimezone(timezone.utc)
        target = find_window(ts_utc)
        if target is None:
            continue
        dm = DISPATCH_RE.search(line)
        if dm and dm.group("agent") == agent:
            target.dispatch_ts.append(ts_utc)
            continue
        if "liveness warning" in line:
            for wm in WORK_AGENT_RE.finditer(line):
                if wm.group("agent") != agent:
                    continue
                q = int(wm.group("q"))
                age = int(wm.group("age"))
                target.max_q = max(target.max_q, q)
                target.max_age = max(target.max_age, age)
                # Wedge heuristic: any queued item aging past 60s. The
                # initial draft required q>=2 to filter transients, but the
                # 2026-05-20 test_41 reproducer showed the canonical wedge
                # shape is q=1 with state=idle and age growing to 140s+ —
                # one stuck item is enough to block all subsequent
                # dispatches under the same sessionKey because openclaw's
                # mycelium-room plugin serializes per-agent group, and the
                # scheduler doesn't re-dispatch on idle-after-burst.
                # 60s comfortably exceeds normal LLM turn time on any
                # supported model, so anything older points at a stalled
                # scheduler rather than a long-running call.
                if q >= 1 and age >= 60:
                    target.wedge_seen = True
    return stats


# ─── Reporting ───────────────────────────────────────────────────────────────

def fmt_gap(gaps: list[float]) -> str:
    if not gaps:
        return "n=0"
    med = statistics.median(gaps)
    return f"n={len(gaps):>2}  med={med:5.1f}s  min={min(gaps):5.1f}s  max={max(gaps):5.1f}s"


def print_report(stats: dict[int, TestStats]) -> None:
    cols = ("test", "tier", "dispatches", "tick gaps (median/min/max)", "max q", "max age", "wedge?")
    print(f"\n{'─' * 110}")
    print(f"{cols[0]:<6}  {cols[1]:<11}  {cols[2]:>10}  {cols[3]:<34}  {cols[4]:>5}  {cols[5]:>9}  {cols[6]}")
    print("─" * 110)
    by_tier: dict[str, list[TestStats]] = {"matrix": [], "distributed": [], "other": []}
    for s in stats.values():
        by_tier[s.tier].append(s)
        wedge = "YES" if s.wedge_seen else ""
        print(
            f"test_{s.window.num:<2}  {s.tier:<11}  "
            f"{len(s.dispatch_ts):>10}  {fmt_gap(s.gaps_s):<34}  "
            f"{s.max_q:>5}  {s.max_age:>7}s  {wedge}"
        )
    print("─" * 110)

    # Tier-level summary
    print(f"\n{'TIER SUMMARY':<14}")
    for tier in ("matrix", "distributed"):
        ts = by_tier[tier]
        if not ts:
            continue
        all_gaps = [g for s in ts for g in s.gaps_s]
        total_dispatch = sum(len(s.dispatch_ts) for s in ts)
        wedges = sum(1 for s in ts if s.wedge_seen)
        max_q = max((s.max_q for s in ts), default=0)
        max_age = max((s.max_age for s in ts), default=0)
        print(f"  {tier:<11}  tests={len(ts):>2}  dispatches={total_dispatch:>3}  "
              f"tick gaps {fmt_gap(all_gaps)}  max q={max_q}  max age={max_age}s  "
              f"wedged tests={wedges}/{len(ts)}")

    # Hypothesis call
    matrix_gaps = [g for s in by_tier["matrix"] for g in s.gaps_s]
    dist_gaps = [g for s in by_tier["distributed"] for g in s.gaps_s]
    dist_wedges = sum(1 for s in by_tier["distributed"] if s.wedge_seen)
    matrix_wedges = sum(1 for s in by_tier["matrix"] if s.wedge_seen)

    print("\nVERDICT")
    if matrix_gaps and dist_gaps:
        m_med = statistics.median(matrix_gaps)
        d_med = statistics.median(dist_gaps)
        gap_ratio = m_med / d_med if d_med else float("inf")
        print(f"  median tick gap: matrix={m_med:.1f}s  distributed={d_med:.1f}s  ratio={gap_ratio:.2f}x")
        if gap_ratio > 1.8:
            print("  → distributed dispatches arrive ≥1.8× faster than matrix → supports H1/H3 (bursty pattern).")
        else:
            print("  → tick gaps similar across tiers → H1/H3 weakened; H2 (cumulative load) more likely.")
    else:
        print("  insufficient data (need both tiers to have completed dispatches).")
    if dist_wedges and not matrix_wedges:
        print(f"  → wedge seen in {dist_wedges} distributed test(s), 0 matrix → distributed-specific trigger.")
    elif dist_wedges and matrix_wedges:
        print(f"  → wedges in both tiers ({matrix_wedges} matrix, {dist_wedges} distributed) → "
              f"load-driven, not test-type-specific (supports H2).")
    elif not dist_wedges and not matrix_wedges:
        print("  → no wedge observed in this run (q<2 or age<60s everywhere).")


# ─── Entrypoint ──────────────────────────────────────────────────────────────

def latest_e2e_log() -> Optional[Path]:
    log_dir = Path.home() / ".mycelium" / "e2e-logs"
    if not log_dir.exists():
        return None
    candidates = sorted(log_dir.glob("e2e_run_*.log"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", type=Path, help="Path to e2e_run_*.log (default: most recent)")
    ap.add_argument("--agent", default="agent-alpha", help="Which agent's queue to analyze (default: agent-alpha)")
    args = ap.parse_args()

    log = args.log or latest_e2e_log()
    if not log or not log.exists():
        print("ERROR: no e2e_run log found; pass one explicitly.", file=sys.stderr)
        return 2
    print(f"e2e log:    {log}")

    windows = parse_test_windows(log)
    if not windows:
        print("ERROR: no SECTION boundaries found in the log.", file=sys.stderr)
        return 2
    print(f"tests seen: {len(windows)}  (test_{windows[0].num} .. test_{windows[-1].num})")
    print(f"agent:      {args.agent}")

    journal = fetch_journal(windows[0].start)
    print(f"journal:    {len(journal)} lines since {windows[0].start.isoformat()}")

    stats = attribute_journal(journal, windows, agent=args.agent)
    print_report(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
