# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cross-channel "home address" tracking for consensus delivery.

When an agent first appears in a Mycelium negotiation session (either via
``coordination_join`` or the first ``coordination_tick`` they receive),
the adapter records the hermes-side ``SessionSource`` it dispatched into
— Telegram chat, Slack channel, Matrix room — keyed by
``(session_room, agent_id)``. When the negotiation concludes the
:func:`route.NotifyHome` action looks up that stash and sends the
consensus summary back through the *other* platform's adapter via the
hermes ``platform_registry`` shared address book.

Mirrors the openclaw ``return-address.ts``/``notify-home.ts`` pair. The
data is intentionally in-memory only — a gateway restart drops home
addresses, mirroring openclaw's behaviour and avoiding a stale entry
sending a consensus into a channel the user has left.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class HomeAddress:
    """A platform-agnostic pointer to where consensus should be posted."""

    platform: str  # e.g. "telegram", "matrix", "discord"
    chat_id: str
    thread_id: str | None = None
    raw_source: Any = None  # original SessionSource for diagnostics


class ReturnAddressBook:
    """Thread-safe stash: ``(session_room, agent_id) → HomeAddress``.

    The hermes gateway runs many adapter tasks concurrently and consensus
    delivery happens from the room SSE task while ticks may still be
    arriving on the session SSE task — so writes can race reads from a
    different task on a different room. Use a single lock; the dict stays
    small (one entry per agent×session) so lock contention is negligible.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._addresses: dict[tuple[str, str], HomeAddress] = {}

    def stash(self, *, session_room: str, agent_id: str, address: HomeAddress) -> None:
        """Idempotent — re-stashing the same agent overwrites the previous
        entry. Same shape as the openclaw plugin's ``stashReturnAddress``.
        """
        with self._lock:
            self._addresses[(session_room, agent_id)] = address

    def lookup(self, *, session_room: str, agent_id: str) -> HomeAddress | None:
        with self._lock:
            return self._addresses.get((session_room, agent_id))

    def drop_session(self, session_room: str) -> None:
        """Remove all entries for *session_room* (post-consensus cleanup)."""
        with self._lock:
            stale = [k for k in self._addresses if k[0] == session_room]
            for k in stale:
                self._addresses.pop(k, None)

    def __len__(self) -> int:  # for tests + debug
        with self._lock:
            return len(self._addresses)
