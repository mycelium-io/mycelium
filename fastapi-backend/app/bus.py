# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
In-process pub/sub bus.

In-process pub/sub for the backend's single always-on process. Producers
(memory/messages/sessions/plan routes) publish dict payloads to a channel; the
SSE ``stream`` route subscribes.

This works because the backend is a single always-on process — producer and
consumer share the same event loop, so an in-memory fan-out is sufficient. It
only has to keep the UI's SSE stream fed.

Channel naming convention is unchanged: ``room:{room_name}`` / ``agent:{handle}``.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


def room_channel(room_name: str) -> str:
    """Canonical channel name for a room."""
    return f"room:{room_name}"


def agent_channel(handle: str) -> str:
    """Canonical channel name for per-agent push notifications."""
    return f"agent:{handle}"


class _Bus:
    """A minimal in-memory channel fan-out.

    Each subscriber gets its own unbounded queue; ``publish`` copies the payload
    into every queue registered on the channel. Delivery is best-effort — a
    dropped subscriber just stops draining its queue and is cleaned up on
    ``unsubscribe``.
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, channel: str) -> asyncio.Queue:
        """Register a new subscriber queue on ``channel``."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(channel, set()).add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue; drop the channel entry when it empties."""
        subs = self._subs.get(channel)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subs.pop(channel, None)

    def publish(self, channel: str, payload: dict) -> None:
        """Fan ``payload`` out to every current subscriber of ``channel``.

        Never raises — SSE delivery is best-effort and must not fail the write
        that triggered it.
        """
        for queue in list(self._subs.get(channel, ())):
            try:
                queue.put_nowait(payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("bus publish to %s dropped: %s", channel, exc)


bus = _Bus()
