# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Logging that never holds up the hub.

The hub logs to stdout, and in the desktop app stdout is a pipe the app's
supervisor drains. When nothing drains it the pipe fills, and a write to it
blocks. Logging writes on the thread that logs, so a request log written on
the event loop would stop every request with it: the hub answered nothing
until it was restarted.

:func:`install` puts each handler on the root logger and uvicorn's behind a
bounded queue. The thread that logs only puts the record in the queue, and a
listener thread does the writing. A listener that's stuck on a full pipe fills
the queue, and further records are dropped, counted and said once the output
moves again. A blocked log loses lines; it never stops the hub.
"""

from __future__ import annotations

import logging
import logging.handlers
import queue

#: How many records may wait to be written before new ones are dropped.
QUEUE_SIZE = 10_000
#: The loggers with handlers of their own: the root, and uvicorn's, which
#: don't propagate to it.
LOGGERS = ("", "uvicorn", "uvicorn.access", "uvicorn.error")


class DroppingQueueHandler(logging.handlers.QueueHandler):
    """A queue handler that drops a record when the queue is full, instead of
    waiting or reporting the error to stderr, which may be the same full pipe."""

    def __init__(self, records: queue.Queue) -> None:
        super().__init__(records)
        self.dropped = 0

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1


class _Listener(logging.handlers.QueueListener):
    """Writes records through the logger's own handlers, and says how many
    were dropped before the next one goes out."""

    def __init__(self, records: queue.Queue, front: DroppingQueueHandler, *handlers) -> None:
        super().__init__(records, *handlers, respect_handler_level=True)
        self.front = front
        self.records: queue.Queue = records

    def handle(self, record: logging.LogRecord) -> None:
        if self.front.dropped:
            lost, self.front.dropped = self.front.dropped, 0
            note = logging.LogRecord(
                record.name,
                logging.WARNING,
                __file__,
                0,
                "(left out %d log lines while the output was blocked)",
                (lost,),
                None,
            )
            super().handle(note)
        super().handle(record)


_listeners: list[_Listener] = []


def install(queue_size: int = QUEUE_SIZE) -> None:
    """Move each of :data:`LOGGERS`' handlers behind a queue of its own. Safe to
    call more than once: a logger already behind a queue is left as it is."""
    for name in LOGGERS:
        logger = logging.getLogger(name)
        handlers = [h for h in logger.handlers if not isinstance(h, DroppingQueueHandler)]
        if not handlers or len(handlers) != len(logger.handlers):
            continue
        records: queue.Queue = queue.Queue(maxsize=queue_size)
        front = DroppingQueueHandler(records)
        listener = _Listener(records, front, *handlers)
        listener.start()
        _listeners.append(listener)
        logger.handlers = [front]


def uninstall() -> None:
    """Stop the listeners after writing what's waiting, and put each logger's
    handlers back."""
    while _listeners:
        listener = _listeners.pop()
        try:
            listener.stop()
        except Exception:  # shutting down; stderr may be the full pipe too
            continue
        for name in LOGGERS:
            logger = logging.getLogger(name)
            if logger.handlers == [listener.front]:
                logger.handlers = list(listener.handlers)
