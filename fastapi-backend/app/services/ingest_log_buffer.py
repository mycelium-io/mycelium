# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""In-memory ring buffer of CFN shared-memories ingest attempts.

Holds the last N forwards to CFN so ``mycelium cfn log`` and ``mycelium cfn
stats`` can surface cost and success signal without tailing backend logs.
The ``audit_events`` table remains the durable record; this buffer is purely
an observability aid and resets on backend restart.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime

from pydantic import BaseModel

_DEFAULT_MAXLEN = 500


class IngestEvent(BaseModel):
    """A single CFN shared-memories forward attempt (success or failure)."""

    timestamp: datetime
    workspace_id: str
    mas_id: str
    agent_id: str | None = None
    request_id: str
    record_count: int
    payload_bytes: int
    estimated_cfn_knowledge_input_tokens: int
    latency_ms: float
    cfn_status: int | None = None
    cfn_message: str | None = None
    error: str | None = None


class IngestLogBuffer:
    """Threadsafe fixed-size deque of :class:`IngestEvent`."""

    def __init__(self, maxlen: int = _DEFAULT_MAXLEN) -> None:
        self._events: deque[IngestEvent] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._started_at = datetime.now(UTC)

    @property
    def started_at(self) -> datetime:
        return self._started_at

    def append(self, event: IngestEvent) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> list[IngestEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_buffer: IngestLogBuffer | None = None


def get_buffer() -> IngestLogBuffer:
    """Return the process-wide ingest log buffer, creating it on first access."""
    global _buffer
    if _buffer is None:
        _buffer = IngestLogBuffer()
    return _buffer
