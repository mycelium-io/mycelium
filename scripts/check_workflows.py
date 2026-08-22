#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
"""Contract checks over .github/workflows — the CI that checks CI.

Three properties, each of which has a way of eroding quietly:

  1. Every `uses:` is pinned to a full commit SHA. A moving tag is a supply
     chain hole: the tag can be repointed at new code that runs with our
     GITHUB_TOKEN, and nothing in the diff shows it moved.
  2. Every workflow declares `permissions:`. Without one the job inherits the
     repository default, which can be write-all — so the blast radius of a
     compromised step is a repo setting rather than something reviewable here.
  3. Every job in ci.yml has a duration budget in .github/ci-budgets.json, and
     every budget names a real job. The budgets are only useful if they can't
     drift away from the jobs they describe.

Pure stdlib and line-oriented so it needs no install step: it reads the
workflow files as text rather than parsing YAML.

    uv run python scripts/check_workflows.py     # exits 1 on any violation
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
BUDGETS_FILE = REPO_ROOT / ".github" / "ci-budgets.json"

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)")
SHA_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
TOP_LEVEL_KEY = re.compile(r"^(?P<key>[a-zA-Z_][a-zA-Z0-9_-]*):")
JOB_KEY = re.compile(r"^  (?P<job>[a-zA-Z_][a-zA-Z0-9_-]*):\s*$")
JOB_NAME = re.compile(r"^    name:\s*(?P<name>.+?)\s*$")


def problems_in(path: Path) -> list[str]:
    """Pinning + permissions violations in one workflow file."""
    found: list[str] = []
    lines = path.read_text().splitlines()

    for lineno, line in enumerate(lines, start=1):
        match = USES.match(line)
        if not match:
            continue
        ref = match.group("ref").strip("\"'")
        # A local composite action (./.github/actions/x) and a digest-pinned
        # container image are already immutable.
        if ref.startswith(("./", "docker://")):
            continue
        if not SHA_PINNED.match(ref):
            found.append(
                f"{path.name}:{lineno}: `uses: {ref}` is not pinned to a "
                f"40-character commit SHA (add `# vN` after it for readability)",
            )

    if not any(TOP_LEVEL_KEY.match(line) and line.startswith("permissions:") for line in lines):
        found.append(
            f"{path.name}: no top-level `permissions:` block — the workflow "
            f"inherits the repository default instead of declaring its own",
        )

    return found


def declared_jobs(path: Path) -> list[str]:
    """Display names of the jobs in a workflow (the `name:`, else the job key).

    These are the names the Actions API reports, which is what ties a budget to
    the job it measures.
    """
    names: list[str] = []
    in_jobs = False
    pending: str | None = None

    for line in path.read_text().splitlines():
        top = TOP_LEVEL_KEY.match(line)
        if top:
            if pending:
                names.append(pending)
                pending = None
            in_jobs = top.group("key") == "jobs"
            continue
        if not in_jobs:
            continue
        job = JOB_KEY.match(line)
        if job:
            if pending:
                names.append(pending)
            pending = job.group("job")
            continue
        named = JOB_NAME.match(line)
        if named and pending:
            names.append(named.group("name").strip("\"'"))
            pending = None

    if pending:
        names.append(pending)
    return names


def budget_problems() -> list[str]:
    """Budgets and CI jobs must name the same set of jobs."""
    budgets = json.loads(BUDGETS_FILE.read_text())
    jobs = set(declared_jobs(WORKFLOW_DIR / "ci.yml"))
    budgeted = set(budgets["jobs"])

    found = [
        f"ci-budgets.json: no budget for CI job {name!r} — add one (the "
        f"timing report can't flag a job it has no baseline for)"
        for name in sorted(jobs - budgeted)
    ]
    found += [
        f"ci-budgets.json: budget for {name!r} matches no job in ci.yml"
        for name in sorted(budgeted - jobs)
    ]
    return found


def main() -> int:
    problems = [p for path in sorted(WORKFLOW_DIR.glob("*.yml")) for p in problems_in(path)]
    problems += budget_problems()

    for problem in problems:
        # `::error` renders as an annotation under Actions, plain text locally.
        print(f"::error::{problem}")

    if problems:
        print(f"\n{len(problems)} workflow hygiene problem(s).")
        return 1

    checked = len(list(WORKFLOW_DIR.glob("*.yml")))
    print(f"{checked} workflow(s): actions SHA-pinned, permissions declared, budgets aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
