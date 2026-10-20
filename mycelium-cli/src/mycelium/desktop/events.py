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

The log is rotated by size: past :data:`MAX_BYTES` it moves to ``.1`` and a
new one starts, so one long run can't grow it without end.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

#: How big the log grows before it is rotated.
MAX_BYTES = 10 * 1024 * 1024
#: How many events may wait to be written before new ones are dropped.
QUEUE_SIZE = 10_000


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
    ) -> None:
        self.log_path = log_path
        self.line = line
        self.stdout = stdout
        self.max_bytes = max_bytes
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=queue_size)
        #: Events lost since the log last said so: a full queue or a failed write.
        self.dropped = 0
        self._log: IO[str] | None = None
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # One log per run, as before.
        self._open("w")
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

    def _rotate(self) -> None:
        if self._log is None:
            return
        try:
            if self._log.tell() < self.max_bytes:
                return
            self._log.close()
            self.log_path.replace(self.log_path.with_suffix(self.log_path.suffix + ".1"))
        except OSError:
            pass
        self._open("w")

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                return
            self._write(event)

    def _write(self, event: dict[str, Any]) -> None:
        # A sign-in on its way to the app (``session_relay``) goes to stdout
        # alone: the log is a file on disk that any program can read.
        logged = {**event, "session": "(withheld)"} if "session" in event else event
        lines = [self.line(logged)]
        if self.dropped:
            lost, self.dropped = self.dropped, 0
            lines.insert(0, f"(left out {lost} lines that couldn't be written in time)")
        if self._log is not None:
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
