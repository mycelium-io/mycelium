# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Asking the person at this machine before the runner starts what a hub asked for.

Anyone who can reach a hub can queue a job for any runner dialed in to it,
and a hub can say anything about who asked. So a launch or a swarm from a hub
the runner doesn't own waits here until it is answered on this machine: the
desktop app shows a dialog, and ``mycelium runner approve|decline`` answers from a
terminal. The question and its answer are files under the runner's folder, so
nothing that reaches this machine over the network can answer it.

A request is ``requests/<job>.json``; its answer is ``<job>.yes`` or ``<job>.no``
beside it.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: How long a request waits for an answer before it is given up on.
WAIT_S = 600.0
#: How often the runner looks for an answer.
CHECK_S = 0.5

#: A job id as the hub makes them. Anything else never becomes a file name.
_JOB_ID = re.compile(r"^[0-9a-f]{4,32}$")


class ApprovalError(Exception):
    """A request that can't be asked or answered, said as a sentence."""


def requests_dir(base: Path | None = None) -> Path:
    if base is None:
        from mycelium.runner.daemon import runner_dir

        base = runner_dir()
    path = base / "requests"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _checked(job_id: str) -> str:
    if not _JOB_ID.match(job_id):
        raise ApprovalError(f"'{job_id}' isn't a job id.")
    return job_id


def ask(job_id: str, request: dict[str, Any], *, base: Path | None = None) -> dict[str, Any]:
    """Write the question for ``job_id``; returns it as written."""
    folder = requests_dir(base)
    body = {"id": _checked(job_id), "asked_at": datetime.now(UTC).isoformat(), **request}
    for stale in (folder / f"{job_id}.yes", folder / f"{job_id}.no"):
        stale.unlink(missing_ok=True)
    path = folder / f"{job_id}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(body, f, indent=2)
    return body


def answer(job_id: str, *, yes: bool, base: Path | None = None) -> dict[str, Any]:
    """Answer a waiting request; returns what it asked."""
    folder = requests_dir(base)
    path = folder / f"{_checked(job_id)}.json"
    try:
        request = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise ApprovalError(f"Nothing is waiting for an answer as {job_id}.") from e
    (folder / f"{job_id}.{'yes' if yes else 'no'}").write_text("")
    return request


def pending(*, base: Path | None = None) -> list[dict[str, Any]]:
    """Requests waiting for an answer, oldest first."""
    folder = requests_dir(base)
    out = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime):
        job_id = path.stem
        if (folder / f"{job_id}.yes").exists() or (folder / f"{job_id}.no").exists():
            continue
        try:
            out.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return out


def wait(
    job_id: str,
    stop: threading.Event,
    *,
    timeout: float = WAIT_S,
    base: Path | None = None,
) -> bool | None:
    """``True`` once approved, ``False`` once declined, ``None`` when nobody answered."""
    folder = requests_dir(base)
    yes, no = folder / f"{_checked(job_id)}.yes", folder / f"{job_id}.no"
    waited = 0.0
    while waited < timeout:
        if yes.exists():
            return True
        if no.exists():
            return False
        if stop.wait(CHECK_S):
            return None
        waited += CHECK_S
    return None


def forget_all(*, base: Path | None = None) -> None:
    """Drop every question and answer, when a runner starts and none can be waiting."""
    for path in requests_dir(base).iterdir():
        if path.suffix in (".json", ".yes", ".no"):
            path.unlink(missing_ok=True)


def forget(job_id: str, *, base: Path | None = None) -> None:
    folder = requests_dir(base)
    for suffix in ("json", "yes", "no"):
        (folder / f"{_checked(job_id)}.{suffix}").unlink(missing_ok=True)
