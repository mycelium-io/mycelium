# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Logging that never holds up the hub.

A handler stands in for a stdout pipe nobody drains: its write blocks until
the test lets it go. With the handlers behind a queue, logging returns at
once, requests still answer, and what couldn't be written is counted and
said once the output moves again.
"""

from __future__ import annotations

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
