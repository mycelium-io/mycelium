# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""TTL sweep for transient event messages (#392).

Events carrying ``metadata.ttl_seconds`` get an ``event_expires_at`` stamp at
write time; this background loop deletes rows past that stamp. Durable kinds
(no TTL) have ``event_expires_at = NULL`` and are never touched. The GET
endpoint independently filters expired rows, so sweep latency is invisible to
readers — this loop just reclaims storage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import delete

from app.database import async_session_maker
from app.models import Message

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 300

_sweep_task: asyncio.Task | None = None


async def sweep_expired_events() -> int:
    """Delete expired event rows. Returns the number of rows removed."""
    async with async_session_maker() as session:
        result = await session.execute(
            delete(Message).where(
                Message.event_expires_at.is_not(None),
                Message.event_expires_at < datetime.now(UTC),
            )
        )
        await session.commit()
        removed = getattr(result, "rowcount", 0) or 0
    if removed:
        logger.info("event sweep removed %d expired event(s)", removed)
    return removed


async def _sweep_loop() -> None:
    while True:
        try:
            await sweep_expired_events()
        except Exception:  # keep the loop alive across transient DB errors
            logger.exception("event sweep iteration failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def start_event_sweep() -> None:
    global _sweep_task
    if _sweep_task is None or _sweep_task.done():
        _sweep_task = asyncio.get_running_loop().create_task(_sweep_loop())


def stop_event_sweep() -> None:
    global _sweep_task
    if _sweep_task is not None and not _sweep_task.done():
        _sweep_task.cancel()
    _sweep_task = None
