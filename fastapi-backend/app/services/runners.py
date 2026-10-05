# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The runners dialed in to this hub, and the jobs queued for them.

A runner is ``mycelium runner`` on someone's machine. It says hello (what it
found there: agent CLIs, herdr, the folders it may start agents in), keeps
saying it as a heartbeat, and long-polls for jobs. The app queues jobs; the
runner takes them one at a time and reports back.

Held in memory, like presence. A runner re-introduces itself on its next
heartbeat after a hub restart, so the only thing a restart loses is jobs that
were queued and not yet taken, and the recent job history.
"""

from __future__ import annotations

import asyncio
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from app.schemas import (
    DeviceSignature,
    FrameworkRead,
    RunnerHello,
    RunnerJobKind,
    RunnerJobRead,
    RunnerJobReport,
    RunnerRead,
)

#: A runner that has not been heard from for this long reads as disconnected.
STALE_AFTER = timedelta(seconds=45)
#: A runner that has not been heard from for this long is dropped from the list.
FORGET_AFTER = timedelta(hours=6)
#: How many jobs each runner's history keeps.
JOB_HISTORY = 50


class RunnerError(Exception):
    """A job or report the registry refused, with a sentence saying why."""


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Entry:
    hello: RunnerHello
    last_seen: datetime
    started_at: datetime
    jobs: OrderedDict[str, RunnerJobRead] = field(default_factory=OrderedDict)
    wake: asyncio.Event = field(default_factory=asyncio.Event)

    def read(self, now: datetime) -> RunnerRead:
        return RunnerRead(
            **self.hello.model_dump(exclude={"pairing_offers"}),
            connected=now - self.last_seen <= STALE_AFTER,
            last_seen=self.last_seen,
            started_at=self.started_at,
        )


class RunnerRegistry:
    """Every runner this hub has heard from recently, keyed by the id it chose."""

    def __init__(self) -> None:
        self._runners: dict[str, _Entry] = {}

    def clear(self) -> None:
        self._runners.clear()

    def _forget_stale(self, now: datetime) -> None:
        for rid in [r for r, e in self._runners.items() if now - e.last_seen > FORGET_AFTER]:
            del self._runners[rid]

    # ── the runner's side ────────────────────────────────────────────────────

    def hello(self, hello: RunnerHello) -> RunnerRead:
        """Record a runner's hello or heartbeat; the jobs it has keep their places."""
        now = _now()
        entry = self._runners.get(hello.id)
        if entry is None:
            entry = _Entry(hello=hello, last_seen=now, started_at=now)
            self._runners[hello.id] = entry
        else:
            entry.hello = hello
            entry.last_seen = now
        return entry.read(now)

    def touch(self, runner_id: str) -> bool:
        entry = self._runners.get(runner_id)
        if entry is None:
            return False
        entry.last_seen = _now()
        return True

    def remove(self, runner_id: str) -> bool:
        entry = self._runners.pop(runner_id, None)
        if entry is not None:
            entry.wake.set()
        return entry is not None

    async def next_job(self, runner_id: str, timeout: float) -> RunnerJobRead | None:
        """The oldest queued job, marked running; waits up to ``timeout`` for one."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout)
        while True:
            entry = self._runners.get(runner_id)
            if entry is None:
                raise RunnerError("unknown runner")
            entry.last_seen = _now()
            for job in entry.jobs.values():
                if job.status == "queued":
                    job.status = "running"
                    job.updated_at = _now()
                    return job
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            entry.wake.clear()
            try:
                await asyncio.wait_for(entry.wake.wait(), timeout=remaining)
            except TimeoutError:
                return None

    def report(self, runner_id: str, job_id: str, report: RunnerJobReport) -> RunnerJobRead:
        entry = self._runners.get(runner_id)
        if entry is None:
            raise RunnerError("unknown runner")
        job = entry.jobs.get(job_id)
        if job is None:
            raise RunnerError("unknown job")
        entry.last_seen = _now()
        job.status = report.status
        if report.result is not None:
            job.result = report.result
        job.error = report.error
        if report.pairing is not None:
            job.pairing = report.pairing
        job.updated_at = _now()
        return job

    # ── the app's side ───────────────────────────────────────────────────────

    def offering(self, code_id: str) -> RunnerRead | None:
        """The connected runner with a live pairing code starting ``code_id``."""
        now = _now()
        wanted = code_id.upper()
        for entry in self._runners.values():
            if wanted in entry.hello.pairing_offers and now - entry.last_seen <= STALE_AFTER:
                return entry.read(now)
        return None

    def get(self, runner_id: str) -> RunnerRead | None:
        entry = self._runners.get(runner_id)
        return entry.read(_now()) if entry is not None else None

    def all(self) -> list[RunnerRead]:
        now = _now()
        self._forget_stale(now)
        return sorted(
            (e.read(now) for e in self._runners.values()),
            key=lambda r: (not r.connected, r.label.lower()),
        )

    def enqueue(
        self,
        runner_id: str,
        kind: RunnerJobKind,
        spec: dict[str, Any],
        *,
        created_by: str | None,
        signature: DeviceSignature | None = None,
    ) -> RunnerJobRead:
        entry = self._runners.get(runner_id)
        if entry is None:
            raise RunnerError("unknown runner")
        now = _now()
        job = RunnerJobRead(
            id=secrets.token_hex(6),
            runner=runner_id,
            kind=kind,
            spec=spec,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            signature=signature,
        )
        entry.jobs[job.id] = job
        while len(entry.jobs) > JOB_HISTORY:
            entry.jobs.popitem(last=False)
        entry.wake.set()
        return job

    def jobs(self, runner_id: str) -> list[RunnerJobRead] | None:
        entry = self._runners.get(runner_id)
        if entry is None:
            return None
        return list(reversed(entry.jobs.values()))

    def job(self, runner_id: str, job_id: str) -> RunnerJobRead | None:
        entry = self._runners.get(runner_id)
        return entry.jobs.get(job_id) if entry is not None else None


registry = RunnerRegistry()


# ── checks the routes share ──────────────────────────────────────────────────


def framework_of(runner: RunnerRead, framework_id: str) -> FrameworkRead | None:
    return next((f for f in runner.frameworks if f.id == framework_id), None)


def check_ready(runner: RunnerRead) -> None:
    if not runner.connected:
        raise RunnerError(
            f"{runner.label} is not connected. Start it there with `mycelium runner`."
        )


def check_framework(runner: RunnerRead, framework_id: str) -> None:
    """Refuse ``framework_id`` when ``runner`` cannot start it on its host."""
    host = runner.host
    if not runner.herdr:
        raise RunnerError(
            f"{host} isn't running on {runner.label}, so it can't start agents. Start it there."
        )
    fw = framework_of(runner, framework_id)
    if fw is None or not fw.installed:
        raise RunnerError(f"{framework_id} is not installed on {runner.label}.")
    if not fw.launchable:
        raise RunnerError(
            f"{fw.name} was found on {runner.label}, but {host} can't start it"
            + (f": {fw.note}" if fw.note else ".")
        )


def _inside(path: str, root: str) -> bool:
    kind = PureWindowsPath if (":" in root[:3] or "\\" in root) else PurePosixPath
    p, r = kind(path), kind(root)
    return p == r or r in p.parents


def check_cwd(runner: RunnerRead, cwd: str | None) -> str | None:
    """``cwd`` when it is inside one of the runner's roots (the first root when unset).

    The runner checks again against the real filesystem; this is so the app
    hears about a folder it may not use before anything is written.
    """
    if not cwd:
        return runner.roots[0] if runner.roots else None
    if ".." in PurePosixPath(cwd.replace("\\", "/")).parts:
        raise RunnerError("The folder can't contain '..'.")
    if not any(_inside(cwd, root) for root in runner.roots):
        allowed = ", ".join(runner.roots) or "none"
        raise RunnerError(
            f"{cwd} is outside the folders {runner.label} may start agents in ({allowed})."
        )
    return cwd
