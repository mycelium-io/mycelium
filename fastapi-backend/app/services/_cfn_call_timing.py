"""Mycelium-side per-call timing accumulator for the CFN ``/decide`` HTTP
client path.

Mirrors the CFN-side ``_request_timing`` module: a contextvar-scoped dict
that ``_cfn_post`` populates with HTTP/transport stage timings, and that
the round handler in ``coordination.py`` reads back when stamping the
trace.

It also ships a tiny background loop-lag sampler that runs concurrently
with the ``/decide`` await so we can attribute "Mycelium's event loop
was blocked" to the right party — separate from "CFN was slow" or "the
network was slow."

Why a contextvar instead of passing a dict around:
    - ``_cfn_post`` is a low-level helper shared by start / decide and we
      don't want to change its public signature
    - ``contextvars`` is asyncio-task-scoped, so concurrent rounds across
      different rooms get independent buckets automatically

Usage in ``coordination.py``:
    cfn_timing_reset()
    lag = await cfn_loop_lag_start(interval_ms=10)
    try:
        result = await decide_negotiation(...)
    finally:
        await cfn_loop_lag_stop(lag)
    snapshot = cfn_timing_snapshot()  # → {http_ms, client_setup_ms, ...}
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

_timing_cv: ContextVar[dict | None] = ContextVar("_cfn_call_timing", default=None)


def cfn_timing_reset() -> dict:
    """Install a fresh timing dict for this async task and return it."""
    new: dict = {}
    _timing_cv.set(new)
    return new


def cfn_timing_stamp(key: str, value) -> None:
    bucket = _timing_cv.get()
    if bucket is None:  # outside a tracked call — never raise
        return
    bucket[key] = value


@contextmanager
def cfn_timing_stage(key: str) -> Iterator[None]:
    """Time the wrapped block (in ms) and accumulate into the call dict."""
    bucket = _timing_cv.get()
    if bucket is None:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        bucket[key] = round(bucket.get(key, 0.0) + elapsed_ms, 2)


def cfn_timing_snapshot() -> dict:
    bucket = _timing_cv.get()
    return dict(bucket) if bucket is not None else {}


# ────────────────────────── loop-lag sampler ──────────────────────────


@dataclass
class _LagSampler:
    """Background task that sleeps in tight loops and records actual wakeup lag.

    A free, unblocked event loop wakes us up within a few hundred µs of the
    requested ``interval``.  Anything substantially over that is loop block
    time — a sync callback or CPU-bound coroutine kept us off the runner.
    """

    interval_s: float
    task: asyncio.Task | None = None
    samples: list[float] = field(default_factory=list)  # observed lag in ms
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def _run(self) -> None:
        # We compare ``loop.time()`` before and after a fixed-duration sleep.
        # Anything beyond ``interval_s`` is loop blocking; record the excess.
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            t0 = loop.time()
            try:
                # Race: sleep vs stop signal so shutdown is prompt.
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
                return  # stop fired
            except TimeoutError:
                pass
            elapsed = loop.time() - t0
            lag_ms = max(0.0, (elapsed - self.interval_s) * 1000.0)
            self.samples.append(lag_ms)


async def cfn_loop_lag_start(interval_ms: float = 10.0) -> _LagSampler:
    """Start sampling event-loop lag in the background.  Returns the sampler."""
    sampler = _LagSampler(interval_s=interval_ms / 1000.0)
    sampler.task = asyncio.create_task(sampler._run(), name="cfn-loop-lag-sampler")
    return sampler


async def cfn_loop_lag_stop(sampler: _LagSampler) -> dict:
    """Stop sampler and merge summary stats into the timing snapshot.

    Returns a small dict with ``samples_n``, ``mean_ms``, ``p95_ms``,
    ``max_ms`` for the sampling window.
    """
    sampler._stop.set()
    if sampler.task is not None:
        try:
            await sampler.task
        except Exception:  # pragma: no cover — never let sampling break the call
            pass
    samples = sampler.samples
    if not samples:
        summary = {
            "loop_lag_samples_n": 0,
            "loop_lag_mean_ms": 0.0,
            "loop_lag_p95_ms": 0.0,
            "loop_lag_max_ms": 0.0,
        }
    else:
        samples_sorted = sorted(samples)
        p95_idx = max(0, round(0.95 * len(samples_sorted)) - 1)
        summary = {
            "loop_lag_samples_n": len(samples),
            "loop_lag_mean_ms": round(sum(samples) / len(samples), 2),
            "loop_lag_p95_ms": round(samples_sorted[p95_idx], 2),
            "loop_lag_max_ms": round(max(samples), 2),
        }
    bucket = _timing_cv.get()
    if bucket is not None:
        bucket.update(summary)
    return summary
