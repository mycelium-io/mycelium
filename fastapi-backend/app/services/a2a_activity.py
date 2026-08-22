# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""In-process record of a room's A2A bridge traffic, for the Network views.

The bridge is the one hop that does not ride SLIM: an outbound call to a remote
agent's endpoint, or an inbound message arriving at the room's own Agent Card.
Neither leaves a trace on the channel telemetry the Network pane reads, so a
bridged turn would otherwise be invisible next to SLIM traffic. This module is
the seam that makes it legible: the responder records each remote call, the
inbound server records each delivered message and card fetch, and the a2a state
route projects both.

Deliberately in-memory and bounded (the last :data:`RING` exchanges per room,
plus lifetime counters). It's telemetry for a live pane, not a record: the room
transcript is the durable one — a bridged reply is already persisted there as a
normal message. A restart resets it.
"""

from __future__ import annotations

import itertools
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: Exchanges kept per room. The pane shows a live tail, not a history.
RING = 50

#: Prompt/reply text is previewed, never stored whole — a bridged turn can carry
#: a long document, and this is a diagnostics pane.
PREVIEW_CHARS = 240

_ids = itertools.count(1)
_lock = threading.Lock()


@dataclass(frozen=True)
class A2aExchange:
    """One bridged turn: a remote call we made, or a message that arrived."""

    id: str
    room: str
    handle: str
    #: ``outbound`` — we called a registered agent's remote endpoint.
    #: ``inbound`` — an external client posted into the room's own A2A card.
    direction: str
    status: str  # ok | error
    at: datetime
    endpoint: str | None = None
    #: The handle whose ``@``-mention triggered the call (outbound only).
    peer: str | None = None
    prompt: str = ""
    reply: str = ""
    #: Why it failed, for ``status == "error"``.
    detail: str | None = None
    duration_ms: int | None = None


@dataclass
class AgentStats:
    """Lifetime call counters for one bridged agent."""

    calls_ok: int = 0
    calls_failed: int = 0
    last_call_at: datetime | None = None


@dataclass(frozen=True)
class RoomTotals:
    """A room's lifetime bridge counters, snapshotted."""

    outbound_ok: int = 0
    outbound_failed: int = 0
    inbound_messages: int = 0
    card_fetches: int = 0
    last_inbound_at: datetime | None = None
    last_card_fetch_at: datetime | None = None


@dataclass
class _RoomState:
    exchanges: deque[A2aExchange] = field(default_factory=lambda: deque(maxlen=RING))
    agents: dict[str, AgentStats] = field(default_factory=dict)
    outbound_ok: int = 0
    outbound_failed: int = 0
    inbound_messages: int = 0
    card_fetches: int = 0
    last_inbound_at: datetime | None = None
    last_card_fetch_at: datetime | None = None


_rooms: dict[str, _RoomState] = {}


def _state(room: str) -> _RoomState:
    return _rooms.setdefault(room, _RoomState())


def _preview(text: str) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= PREVIEW_CHARS else cleaned[: PREVIEW_CHARS - 1] + "…"


def _norm(handle: str | None) -> str:
    return (handle or "").strip().lstrip("@").lower()


def record_outbound(
    room: str,
    handle: str,
    *,
    status: str,
    endpoint: str | None = None,
    peer: str | None = None,
    prompt: str = "",
    reply: str = "",
    detail: str | None = None,
    duration_ms: int | None = None,
) -> A2aExchange:
    """Record a call this hub made to a registered agent's remote endpoint."""
    handle = _norm(handle)
    at = datetime.now(UTC)
    exchange = A2aExchange(
        id=f"a2a-{next(_ids)}",
        room=room,
        handle=handle,
        direction="outbound",
        status=status,
        at=at,
        endpoint=endpoint,
        peer=_norm(peer) or None,
        prompt=_preview(prompt),
        reply=_preview(reply),
        detail=detail,
        duration_ms=duration_ms,
    )
    with _lock:
        state = _state(room)
        state.exchanges.append(exchange)
        stats = state.agents.setdefault(handle, AgentStats())
        stats.last_call_at = at
        if status == "ok":
            state.outbound_ok += 1
            stats.calls_ok += 1
        else:
            state.outbound_failed += 1
            stats.calls_failed += 1
    return exchange


def record_inbound(
    room: str,
    *,
    handle: str,
    status: str,
    prompt: str = "",
    reply: str = "",
    detail: str | None = None,
) -> A2aExchange:
    """Record a message an external A2A client sent to the room's own card."""
    at = datetime.now(UTC)
    exchange = A2aExchange(
        id=f"a2a-{next(_ids)}",
        room=room,
        handle=_norm(handle),
        direction="inbound",
        status=status,
        at=at,
        prompt=_preview(prompt),
        reply=_preview(reply),
        detail=detail,
    )
    with _lock:
        state = _state(room)
        state.exchanges.append(exchange)
        state.inbound_messages += 1
        state.last_inbound_at = at
    return exchange


def record_card_fetch(room: str) -> None:
    """Record that someone read the room's Agent Card — the room is discoverable."""
    with _lock:
        state = _state(room)
        state.card_fetches += 1
        state.last_card_fetch_at = datetime.now(UTC)


def recent(room: str, limit: int = RING) -> list[A2aExchange]:
    """The room's most recent exchanges, newest last."""
    with _lock:
        exchanges = list(_state(room).exchanges)
    return exchanges[-limit:] if limit > 0 else []


def agent_stats(room: str, handle: str) -> AgentStats:
    """Lifetime call counters for one bridged agent (zeroed when it has none)."""
    with _lock:
        return _state(room).agents.get(_norm(handle), AgentStats())


def totals(room: str) -> RoomTotals:
    """The room's lifetime counters."""
    with _lock:
        state = _state(room)
        return RoomTotals(
            outbound_ok=state.outbound_ok,
            outbound_failed=state.outbound_failed,
            inbound_messages=state.inbound_messages,
            card_fetches=state.card_fetches,
            last_inbound_at=state.last_inbound_at,
            last_card_fetch_at=state.last_card_fetch_at,
        )


def clear() -> None:
    """Drop every room's activity — test isolation and nothing else."""
    with _lock:
        _rooms.clear()
