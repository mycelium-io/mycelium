# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where the supervisor's events go: its log file, and for the app, stdout.

Every program the supervisor runs writes its output to a pipe, and a thread
per program drains that pipe into :meth:`EventWriter.emit`. If ``emit`` ever
waited, on a full disk, a slow log or an app that stopped reading the
supervisor's stdout, the readers would wait behind it, the pipes would fill,
and each program would block on its next write. The hub blocked like that
answers nothing. So ``emit`` only puts the event in a bounded queue, and one
thread of its own does the writing. A write that fails, or a queue that's
full, loses lines rather than stopping anyone; the log says how many.

The log is never wiped. A new run moves the last one to ``.1`` (``.1`` to
``.2``, and so on, keeping :data:`KEEP`), so what happened before a crash and
a relaunch is still there to read. A run that grows past :data:`MAX_BYTES`
rotates the same way, so one long run can't grow it without end.

What the file leaves out is the noise that pushed everything else out of it:
a request the app's own sync and runner make every few seconds, when it
succeeds (:func:`routine`). A failed one is written, and so is everything else.
"""

from __future__ import annotations

import json
import queue
import re
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import IO, Any

#: How big the log grows before it is rotated.
MAX_BYTES = 10 * 1024 * 1024
#: How many earlier logs are kept beside the current one (``.1`` is the newest).
KEEP = 5
#: How many events may wait to be written before new ones are dropped.
QUEUE_SIZE = 10_000

#: A request the hub logs that the app makes on its own, every few seconds,
#: answered without an error: the herdr sync pass (each room's presence and
#: wakes, and each agent's notes) and the runner's heartbeat and job poll.
_ROUTINE = re.compile(
    r'"(?:GET|POST) (?:'
    r"/api/rooms/[^/ ]+/sessions/herdr-(?:presence|wakes)"
    r"|/api/rooms/[^/ ]+/memory/agents/[^ ]+"
    r"|/api/runners(?:/[^/ ]+/jobs/next)?"
    r"|/health"
    r')(?:\?[^ ]*)? HTTP/[\d.]+" [23]\d\d\b'
)


def routine(event: dict[str, Any]) -> bool:
    """Whether ``event`` is a successful request the app's own polling makes,
    left out of the log file (the app is still sent it)."""
    return (
        event.get("type") == "log"
        and event.get("component") == "hub"
        and bool(_ROUTINE.search(str(event.get("line", ""))))
    )


def shift(log_path: Path, keep: int = KEEP) -> None:
    """Move ``log_path`` to ``.1``, ``.1`` to ``.2`` and so on, dropping the
    oldest past ``keep``. Nothing is lost that fits; failures are left alone."""

    def older(n: int) -> Path:
        return log_path.with_suffix(f"{log_path.suffix}.{n}")

    try:
        older(keep).unlink(missing_ok=True)
        for n in range(keep - 1, 0, -1):
            if older(n).exists():
                older(n).replace(older(n + 1))
        if log_path.exists() and log_path.stat().st_size:
            log_path.replace(older(1))
    except OSError:
        pass


class EventWriter:
    """Write events to a log file and, optionally, as JSON lines to ``stdout``,
    from a thread of its own."""

    def __init__(
        self,
        log_path: Path,
        *,
        line: Callable[[dict[str, Any]], str],
        stdout: IO[str] | None = None,
        max_bytes: int = MAX_BYTES,
        queue_size: int = QUEUE_SIZE,
        keep: int = KEEP,
        leave_out: Callable[[dict[str, Any]], bool] = routine,
    ) -> None:
        self.log_path = log_path
        self.line = line
        self.stdout = stdout
        self.max_bytes = max_bytes
        self.keep = keep
        self.leave_out = leave_out
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=queue_size)
        #: Events lost since the log last said so: a full queue or a failed write.
        self.dropped = 0
        self._log: IO[str] | None = None
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # A log per run, the last ones kept: a relaunch after a crash must not
        # wipe what the crashed run said.
        shift(log_path, keep)
        self._open("w")
        self._started()
        self._thread = threading.Thread(target=self._run, name="events", daemon=True)
        self._thread.start()

    def emit(self, event: dict[str, Any]) -> None:
        """Hand ``event`` over to be written. Never waits."""
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    def close(self, timeout: float = 5.0) -> None:
        """Write what's waiting, then stop."""
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:
            return
        self._thread.join(timeout=timeout)

    def _open(self, mode: str) -> None:
        try:
            self._log = self.log_path.open(mode, encoding="utf-8")
        except OSError:
            self._log = None

    def _started(self, how: str = "started") -> None:
        """The date heads each file, since its lines carry only the time."""
        if self._log is None:
            return
        try:
            self._log.write(
                f"--- {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}: Mycelium {how}\n"
            )
            self._log.flush()
        except (OSError, ValueError):
            pass

    def _rotate(self) -> None:
        if self._log is None:
            return
        try:
            if self._log.tell() < self.max_bytes:
                return
            self._log.close()
        except OSError:
            pass
        shift(self.log_path, self.keep)
        self._open("w")
        self._started("still running; earlier lines are in the .1 file")

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                return
            self._write(event)

    def _write(self, event: dict[str, Any]) -> None:
        if self._log is not None and not self.leave_out(event):
            lines = [self.line(event)]
            if self.dropped:
                lost, self.dropped = self.dropped, 0
                lines.insert(0, f"(left out {lost} lines that couldn't be written in time)")
            try:
                self._rotate()
                if self._log is not None:
                    self._log.write("".join(text + "\n" for text in lines))
                    self._log.flush()
            except (OSError, ValueError):
                self.dropped += 1
        if self.stdout is not None:
            try:
                self.stdout.write(json.dumps(event) + "\n")
                self.stdout.flush()
            except (OSError, ValueError):
                # The app went away: nobody is reading, so stop writing to it.
                self.stdout = None
