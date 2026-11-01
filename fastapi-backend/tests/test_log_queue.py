# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Logging that never holds up the hub.

A handler stands in for a stdout pipe nobody drains: its write blocks until
the test lets it go. With the handlers behind a queue, logging returns at
once, requests still answer, and what couldn't be written is counted and
said once the output moves again.
"""

from __future__ import annotations

import io
import logging
import threading
import time

import pytest
from httpx import AsyncClient

from app.services import log_queue


class BlockedHandler(logging.Handler):
    """A handler whose write waits, as one to a full pipe does."""

    def __init__(self) -> None:
        super().__init__()
        self.free = threading.Event()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.free.wait()
        self.lines.append(record.getMessage())


@pytest.fixture
def blocked():
    root = logging.getLogger()
    before = list(root.handlers)
    handler = BlockedHandler()
    root.handlers = [handler]
    yield handler
    handler.free.set()
    log_queue.uninstall()
    root.handlers = before


@pytest.mark.asyncio
async def test_a_blocked_output_never_holds_up_logging_or_requests(blocked, client: AsyncClient):
    log_queue.install(queue_size=100)
    logger = logging.getLogger("app.test")
    started = time.monotonic()
    for i in range(5_000):
        logger.warning("line %d", i)
    # The thread that logs only queues; it never waits on the output.
    assert time.monotonic() - started < 2.0
    assert (await client.get("/health")).status_code == 200

    # Once the output moves, what was queued is written, and what was dropped
    # is said rather than lost without a word.
    blocked.free.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not all(
        lis.records.empty() for lis in log_queue._listeners
    ):
        time.sleep(0.01)
    logger.warning("after")
    while time.monotonic() < deadline and "after" not in blocked.lines:
        time.sleep(0.01)
    assert "after" in blocked.lines
    assert any(line.startswith("(left out ") for line in blocked.lines)


def test_install_twice_leaves_one_queue_and_uninstall_puts_handlers_back(blocked):
    blocked.free.set()
    root = logging.getLogger()
    before = list(root.handlers)
    log_queue.install()
    log_queue.install()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], log_queue.DroppingQueueHandler)
    log_queue.uninstall()
    assert root.handlers == before


def _drained(stream: io.StringIO, text: str) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and text not in stream.getvalue():
        time.sleep(0.01)
    return text in stream.getvalue()


def test_uvicorns_access_lines_and_tracebacks_come_through_the_queue(capsys):
    # uvicorn's access formatter unpacks the record's args, and a traceback
    # needs exc_info: both must survive the queue, or every request's line
    # fails and the failure goes to stderr, the pipe this is protecting.
    from uvicorn.logging import AccessFormatter

    access = logging.getLogger("uvicorn.access")
    root = logging.getLogger()
    saved = (list(access.handlers), access.propagate, list(root.handlers))
    access_out, root_out = io.StringIO(), io.StringIO()
    access_handler = logging.StreamHandler(access_out)
    access_handler.setFormatter(
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    )
    access.handlers, access.propagate = [access_handler], False
    root.handlers = [logging.StreamHandler(root_out)]
    try:
        log_queue.install()
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/health", "1.1", 200)
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logging.getLogger("app.test").exception("it failed")
        assert _drained(access_out, '"GET /health HTTP/1.1" 200')
        assert _drained(root_out, "RuntimeError: boom")
    finally:
        log_queue.uninstall()
        access.handlers, access.propagate, root.handlers = saved
    assert "Logging error" not in capsys.readouterr().err
