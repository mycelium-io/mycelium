#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
"""Report how long this CI run took, per job, against committed budgets.

CI being fast is a property worth keeping, and the way it erodes is invisible:
nobody notices twenty seconds, and a year of twenty seconds is a coffee break
per PR. This reads the run's own jobs back from the Actions API, writes a table
into the run summary, and raises a ::warning:: for anything over budget.

It never fails the run. Timing is information, not a gate — a slow PR should
merge, it should just say it was slow. Budgets live in .github/ci-budgets.json.

Reads GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT and
appends to GITHUB_STEP_SUMMARY; run under Actions, not locally.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUDGETS_FILE = REPO_ROOT / ".github" / "ci-budgets.json"
API = "https://api.github.com"

# This job is still running while it reports, so it has no end time of its own
# and cannot be part of the critical path it measures.
SELF = os.environ.get("CI_TIMING_JOB_NAME", "CI timing")


def fetch_jobs() -> list[dict]:
    """Every job of this run attempt, from the Actions API."""
    repo = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    url = f"{API}/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"

    request = urllib.request.Request(url)  # noqa: S310 — fixed https API host
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.load(response)["jobs"]


def parse(stamp: str | None) -> datetime | None:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None


def duration(job: dict) -> int | None:
    """Wall-clock seconds the job ran, or None if it never finished."""
    started, completed = parse(job.get("started_at")), parse(job.get("completed_at"))
    if not started or not completed:
        return None
    return max(0, round((completed - started).total_seconds()))


def emit(lines: list[str]) -> None:
    """Append markdown to the run summary (and echo it into the log)."""
    body = "\n".join(lines) + "\n"
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as handle:
            handle.write(body)
    print(body)


def main() -> int:
    budgets = json.loads(BUDGETS_FILE.read_text())
    job_budgets: dict[str, int] = budgets["jobs"]

    try:
        jobs = [job for job in fetch_jobs() if job["name"] != SELF]
    except (urllib.error.URLError, KeyError, TimeoutError) as err:
        # The report is a courtesy; losing it must not colour the run.
        print(f"::notice::CI timing report unavailable: {err}")
        return 0

    rows: list[str] = []
    warnings: list[str] = []
    slowest: tuple[int, str] | None = None

    for job in sorted(jobs, key=lambda j: -(duration(j) or 0)):
        name = job["name"]
        seconds = duration(job)
        budget = job_budgets.get(name)

        if job["conclusion"] == "skipped" or seconds is None:
            rows.append(f"| {name} | — | {budget or '—'}s | skipped |")
            continue

        if slowest is None or seconds > slowest[0]:
            slowest = (seconds, name)

        if budget is None:
            verdict = "no budget"
        elif seconds > budget:
            verdict = f"**over by {seconds - budget}s**"
            warnings.append(f"{name} took {seconds}s (budget {budget}s)")
        else:
            verdict = f"{round(100 * seconds / budget)}% of budget"
        rows.append(f"| {name} | {seconds}s | {budget or '—'}s | {verdict} |")

    starts = [parse(job.get("started_at")) for job in jobs]
    ends = [parse(job.get("completed_at")) for job in jobs]
    known = [(s, e) for s, e in zip(starts, ends, strict=True) if s and e]
    wall = (
        round((max(e for _, e in known) - min(s for s, _ in known)).total_seconds()) if known else 0
    )
    wall_budget = budgets["wall_clock_seconds"]

    tail = f" — {slowest[1]} owns the tail at {slowest[0]}s" if slowest else ""
    verdict = (
        f"⚠️ **{wall}s**, over the {wall_budget}s baseline{tail}"
        if wall > wall_budget
        else f"✅ **{wall}s**, within the {wall_budget}s baseline{tail}"
    )

    emit(
        [
            "## CI timing",
            "",
            f"Critical path: {verdict}",
            "",
            "| Job | Duration | Budget | |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
            "_Budgets are in `.github/ci-budgets.json` and never fail a run._",
        ],
    )

    if wall > wall_budget:
        print(f"::warning::CI critical path was {wall}s, over the {wall_budget}s baseline{tail}")
    for warning in warnings:
        print(f"::warning::{warning}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
