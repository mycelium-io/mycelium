# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the TTL event sweep (app/services/event_sweep.py).

Node-free: the sweep is a thin loop over ``in_memory_store``; here we drive the one
iteration directly and pin the start/stop task lifecycle.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.services import event_sweep
from app.services import in_memory_store as ls


@pytest.mark.asyncio
async def test_sweep_removes_expired_and_spares_durable() -> None:
    now = datetime.now(UTC)
    ls.add_message(
        "room-a",
        ls.StoredMessage(
            sender_handle="a",
            message_type="event",
            content="expired",
            event_expires_at=now - timedelta(seconds=1),
        ),
    )
    ls.add_message(
        "room-a",
        ls.StoredMessage(sender_handle="a", message_type="broadcast", content="durable"),
    )

    removed = await event_sweep.sweep_expired_events()
    assert removed == 1
    assert [m.content for m in ls.list_messages("room-a")] == ["durable"]


@pytest.mark.asyncio
async def test_sweep_returns_zero_when_nothing_expired() -> None:
    ls.add_message(
        "room-a",
        ls.StoredMessage(sender_handle="a", message_type="broadcast", content="keep"),
    )
    assert await event_sweep.sweep_expired_events() == 0


@pytest.mark.asyncio
async def test_start_is_idempotent_and_stop_cancels() -> None:
    event_sweep.start_event_sweep()
    task = event_sweep._sweep_task
    assert task is not None and not task.done()

    # A second start does not spawn a competing loop.
    event_sweep.start_event_sweep()
    assert event_sweep._sweep_task is task

    event_sweep.stop_event_sweep()
    assert event_sweep._sweep_task is None
    await asyncio.sleep(0)  # let the cancellation propagate
    assert task.cancelled() or task.done()
