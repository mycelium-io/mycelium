# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""In-memory daemon state — surfaced via the health endpoint."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunningProc:
    """A live ``claude -p`` subprocess for one agent — used by control verbs."""

    process: Any  # asyncio.subprocess.Process — typed Any to keep state.py import-light
    started_at: float
    prompt: str
    sender: str
    room: str


@dataclass
class DaemonState:
    """Shared runtime state for the daemon — read by the health endpoint.

    Per-handle locks serialize dispatches so two SSE deliveries for the same
    agent never race over its ``cwd``. Recent-dispatch deques back the rate
    limit that approximates the v0 chain-depth cap.
    """

    started_at: float = field(default_factory=time.monotonic)
    rooms_connected: set[str] = field(default_factory=set)
    rooms_configured: list[str] = field(default_factory=list)
    handle_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    seen_message_ids: deque[str] = field(default_factory=lambda: deque(maxlen=2048))
    recent_dispatches: dict[str, deque[float]] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=32))
    )
    budget_used_usd: dict[tuple[str, str], float] = field(default_factory=dict)
    last_dispatch: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None
    errors_last_hour: deque[float] = field(default_factory=lambda: deque(maxlen=1024))
    running: dict[str, RunningProc] = field(default_factory=dict)
    stopping: asyncio.Event = field(default_factory=asyncio.Event)
    reload_requested: asyncio.Event = field(default_factory=asyncio.Event)
    daemon_cfg: Any = field(default=None)  # DaemonConfig — set by runner after load

    def lock_for(self, handle: str) -> asyncio.Lock:
        lock = self.handle_locks.get(handle)
        if lock is None:
            lock = asyncio.Lock()
            self.handle_locks[handle] = lock
        return lock

    def record_dispatch(
        self,
        *,
        handle: str,
        room: str,
        result: str,
        duration_s: float,
        cost_usd: float,
    ) -> None:
        self.last_dispatch = {
            "agent": handle,
            "room": room,
            "ts": time.time(),
            "duration_s": duration_s,
            "result": result,
            "cost_usd": cost_usd,
        }

    def record_error(self, where: str, exc: BaseException) -> None:
        self.last_error = {
            "where": where,
            "type": type(exc).__name__,
            "msg": str(exc),
            "ts": time.time(),
        }
        self.errors_last_hour.append(time.monotonic())

    def errors_in_last_hour(self) -> int:
        cutoff = time.monotonic() - 3600
        while self.errors_last_hour and self.errors_last_hour[0] < cutoff:
            self.errors_last_hour.popleft()
        return len(self.errors_last_hour)
