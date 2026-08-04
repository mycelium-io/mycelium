# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""TTL sweep for transient event messages (#392).

Events carrying ``metadata.ttl_seconds`` get an ``event_expires_at`` stamp at
write time; this background loop drops messages past that stamp. Durable kinds
(no TTL) have ``event_expires_at = None`` and are never touched. The GET
endpoint independently filters expired messages, so sweep latency is invisible
to readers — this loop just reclaims memory.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.services import local_state

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 300

_sweep_task: asyncio.Task | None = None


async def sweep_expired_events() -> int:
    """Delete expired event messages. Returns the number removed."""
    removed = local_state.sweep_expired_messages(datetime.now(UTC))
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
