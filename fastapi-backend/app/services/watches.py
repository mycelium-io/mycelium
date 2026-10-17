# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Agents' terminals being watched from the app: the latest screen of each.

A watch is a runner job (``watch``): the app asks to see an agent's terminal,
the runner asks the person at that machine, and only after a yes does it send
the agent's screen here, a few times a second, for whoever asked to read. The
hub keeps the newest screen and nothing older, in memory, like presence.

A watch ends when the viewer closes it, when nobody has read it for a while
(a closed tab doesn't always say so), when the agent's pane goes, or after
``MAX_WATCH``. The runner hears on its next send and stops sending.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.schemas import TerminalScreen, WatchRead

#: The longest one watch lasts; the viewer asks again for more.
MAX_WATCH = timedelta(minutes=30)
#: A watch nobody has read for this long has lost its viewer.
VIEWER_GONE_AFTER = timedelta(seconds=30)
#: The largest screen kept, in characters (a screen with its colors).
MAX_SCREEN = 200_000


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Watch:
    runner: str
    #: Handed only to whoever asked to watch: reading and closing need it, so
    #: the job's id (which the jobs list shows) is not enough to read the screen.
    token: str
    started_at: datetime
    viewer_seen: datetime
    #: When the first screen came, after the yes; the time limit counts from here.
    sharing_since: datetime | None = None
    screen: TerminalScreen | None = None
    ended: str | None = None
    changed: asyncio.Event = field(default_factory=asyncio.Event)


class WatchRegistry:
    """The watches this hub is carrying, keyed by their job's id."""

    def __init__(self) -> None:
        self._watches: dict[str, _Watch] = {}

    def clear(self) -> None:
        self._watches.clear()

    def open(self, job_id: str, runner_id: str) -> str:
        """Start carrying a watch; returns the token its viewer reads it with."""
        self._forget_old()
        now = _now()
        token = secrets.token_urlsafe(24)
        self._watches[job_id] = _Watch(
            runner=runner_id, token=token, started_at=now, viewer_seen=now
        )
        return token

    def _viewed(self, job_id: str, runner_id: str, token: str | None) -> _Watch | None:
        """The watch, for the viewer holding its token; ``None`` for anyone else."""
        watch = self._live(job_id, runner_id)
        if watch is None or not token or not secrets.compare_digest(token, watch.token):
            return None
        return watch

    def _live(self, job_id: str, runner_id: str) -> _Watch | None:
        watch = self._watches.get(job_id)
        if watch is None or watch.runner != runner_id:
            return None
        now = _now()
        if watch.ended is None and watch.sharing_since and now - watch.sharing_since > MAX_WATCH:
            self._end(watch, "Watched for 30 minutes. Open it again to keep watching.")
        elif watch.ended is None and now - watch.viewer_seen > VIEWER_GONE_AFTER:
            self._end(watch, "Nobody was watching.")
        return watch

    @staticmethod
    def _end(watch: _Watch, why: str) -> None:
        watch.ended = why
        watch.changed.set()

    # ── the runner's side ────────────────────────────────────────────────────

    def send(self, runner_id: str, job_id: str, text: str, ended: str | None = None) -> bool:
        """Take a new screen; ``False`` when the watch is over and the runner should stop."""
        watch = self._live(job_id, runner_id)
        if watch is None or watch.ended is not None:
            return False
        seq = (watch.screen.seq + 1) if watch.screen else 1
        watch.screen = TerminalScreen(seq=seq, text=text[-MAX_SCREEN:], at=_now())
        watch.sharing_since = watch.sharing_since or watch.screen.at
        if ended:
            self._end(watch, ended)
            return False
        watch.changed.set()
        return True

    # ── the viewer's side ────────────────────────────────────────────────────

    async def read(
        self, runner_id: str, job_id: str, token: str | None, after: int, timeout: float
    ) -> WatchRead | None:
        """The screen after ``after``, waiting up to ``timeout`` for one.

        ``None`` for a watch that isn't there or a ``token`` that isn't its own.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout)
        while True:
            watch = self._viewed(job_id, runner_id, token)
            if watch is None:
                return None
            watch.viewer_seen = _now()
            newer = watch.screen is not None and watch.screen.seq > after
            remaining = deadline - loop.time()
            if newer or watch.ended is not None or remaining <= 0:
                return WatchRead(
                    id=job_id, screen=watch.screen if newer else None, ended=watch.ended
                )
            watch.changed.clear()
            try:
                await asyncio.wait_for(watch.changed.wait(), timeout=min(remaining, 10.0))
            except TimeoutError:
                continue

    def failed(self, job_id: str, why: str) -> None:
        """The machine declined, or couldn't share it: the viewer hears why."""
        watch = self._watches.get(job_id)
        if watch is not None and watch.ended is None:
            self._end(watch, why)

    def close(self, runner_id: str, job_id: str, token: str | None) -> bool:
        watch = self._viewed(job_id, runner_id, token)
        if watch is None:
            return False
        if watch.ended is None:
            self._end(watch, "Closed.")
        return True

    def _forget_old(self) -> None:
        """Drop watches nobody has read for a long while, so the registry doesn't grow."""
        cutoff = _now() - MAX_WATCH
        for job_id in [j for j, w in self._watches.items() if w.viewer_seen < cutoff]:
            del self._watches[job_id]


watches = WatchRegistry()
