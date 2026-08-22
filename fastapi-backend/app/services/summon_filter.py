# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The summon-filter extension point: is this ``@`` a summon, or just a mention?

A room treats every ``@handle`` as a wake. This is the seam where an engine can
say otherwise — the contract the room's summon path calls, and the one a guard
engine implements against. It sits between the generic lifecycle bus
(:mod:`app.services.engine_events`, which knows nothing about summons) and any
particular guard (:mod:`app.services.summonguard`, which knows nothing about how
the room dispatches).

**The room calls this module, never an engine.** The core summon path — the
persister's trigger-watcher and ``await``'s long-poll — imports the contract and
nothing else, so deleting every guard from the tree leaves the room importable
and working. With no filter installed :func:`decide` wakes everything, which is
the pre-guard behaviour exactly.

**The verdict vocabulary is open.** :data:`WAKE`, :data:`MENTION` and
:data:`ABSTAIN` are what exists today; a later engine wanting ``defer`` or
``escalate`` adds a value without this module changing, because the merge treats
anything it does not recognise as *no opinion* rather than an error. A filter
returning a verdict this version has never heard of degrades to a wake — never a
crash, and never a silent suppression.

**Merge policy is fail-open, and deliberately so.** A suppression means an agent
silently never gets a turn: a missed summon stalls the room, a spurious wake
costs one turn. So a handle sleeps only when some filter says ``mention`` and no
filter says ``wake``; abstentions and unrecognised answers carry no weight, and a
filter that raises fails the whole room open. This is one policy for every room —
see the PR notes for why a per-room policy waits for a second guard to justify it.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.services.engine_events import SUMMON_FILTER, lifecycle

logger = logging.getLogger(__name__)

#: Serve the message as the handle's turn — the room's default for every mention.
WAKE = "wake"
#: Record the message and let the handle sleep: it was named, not asked.
MENTION = "mention"
#: This filter has no opinion; leave the decision to the others (or the default).
ABSTAIN = "abstain"

#: How many verdicts per room the introspection surface keeps. Small on purpose:
#: this is a "why didn't @alice wake?" window, not an audit log — the transcript
#: is the durable record.
_VERDICT_HISTORY = 100


def norm(handle: str) -> str:
    """Fold a handle to its comparable form (``@Alice`` → ``alice``)."""
    return handle.strip().lstrip("@").lower()


def now() -> str:
    """Timestamp for a verdict, in the store's one format."""
    return datetime.now(UTC).isoformat()


# ── The contract types (pure) ────────────────────────────────────────────────


@dataclass(frozen=True)
class SummonContext:
    """What a filter is asked to judge: one message, its mentioned handles."""

    room: str
    message_id: str
    sender: str
    text: str
    handles: tuple[str, ...]


@dataclass
class SummonVerdict:
    """One message's decisions, plus how they were reached."""

    room: str
    message_id: str
    sender: str
    text: str
    #: handle -> :data:`WAKE` | :data:`MENTION`
    decisions: dict[str, str]
    #: handle -> one-line justification (empty for short-circuited wakes)
    reasons: dict[str, str] = field(default_factory=dict)
    #: How it was reached — an engine's own label (``pi``, ``fail-open``, …).
    source: str = ""
    decided_at: str = ""

    def wakes(self, handle: str) -> bool:
        """True unless this verdict explicitly classified ``handle`` as provenance."""
        return self.decisions.get(norm(handle), WAKE) != MENTION

    def as_dict(self) -> dict[str, Any]:
        return {
            "room": self.room,
            "message_id": self.message_id,
            "sender": self.sender,
            "text": self.text,
            "decisions": dict(self.decisions),
            "reasons": dict(self.reasons),
            "source": self.source,
            "decided_at": self.decided_at,
        }


#: What an installed filter is: judge a message, answer per handle. Async because
#: a real judgement is a model call, and the summon path is async either side.
SummonFilter = Callable[[SummonContext], Awaitable[Mapping[str, str]]]


# ── Verdict store ────────────────────────────────────────────────────────────


class VerdictStore:
    """Per-room verdicts by message id, with waiters for one being decided.

    A filter publishes on the ingest path; ``await`` needs the same answer a
    moment later. Rather than judge twice (and risk the two paths disagreeing),
    the poll waits here on the event a publish sets.

    The store is shared across every filter in a room, so it is invalidated
    whenever that room's filter set changes: a verdict is only meaningful as the
    output of the filters that produced it, and one outliving its author would
    keep suppressing wakes on an engine's behalf after the engine was removed.
    """

    def __init__(self, history: int = _VERDICT_HISTORY) -> None:
        self._history = history
        self._by_room: dict[str, OrderedDict[str, SummonVerdict]] = {}
        self._waiters: dict[tuple[str, str], asyncio.Event] = {}

    def _event(self, room: str, message_id: str) -> asyncio.Event:
        return self._waiters.setdefault((room, message_id), asyncio.Event())

    def begin(self, room: str, message_id: str) -> None:
        """Mark a judgement in flight so a waiter blocks instead of failing open."""
        self._event(room, message_id)

    def put(self, verdict: SummonVerdict) -> None:
        room = self._by_room.setdefault(verdict.room, OrderedDict())
        room[verdict.message_id] = verdict
        while len(room) > self._history:
            room.popitem(last=False)
        self._event(verdict.room, verdict.message_id).set()

    def get(self, room: str, message_id: str) -> SummonVerdict | None:
        return self._by_room.get(room, {}).get(message_id)

    def pending(self, room: str, message_id: str) -> bool:
        """True when a judgement was started for this message and hasn't landed."""
        event = self._waiters.get((room, message_id))
        return event is not None and not event.is_set()

    async def wait(self, room: str, message_id: str, timeout_s: float) -> SummonVerdict | None:
        """The verdict for a message, waiting up to ``timeout_s`` for one in flight."""
        existing = self.get(room, message_id)
        if existing is not None:
            return existing
        if not self.pending(room, message_id):
            return None
        try:
            await asyncio.wait_for(self._event(room, message_id).wait(), timeout=timeout_s)
        except TimeoutError:
            return None
        return self.get(room, message_id)

    def recent(self, room: str, limit: int = 20) -> list[SummonVerdict]:
        """Most recent verdicts for ``room``, newest first."""
        return list(reversed(list(self._by_room.get(room, {}).values())))[:limit]

    def forget_room(self, room: str) -> None:
        """Drop ``room``'s verdicts and release anything waiting on one.

        Waiters are released rather than left to time out: with the filter set
        changed, nothing is going to publish the answer they are waiting for, and
        the fail-open default is the right one to reach immediately.
        """
        self._by_room.pop(room, None)
        for (waiting_room, _mid), event in list(self._waiters.items()):
            if waiting_room == room:
                event.set()
        self._waiters = {key: e for key, e in self._waiters.items() if key[0] != room}

    def clear(self) -> None:
        self._by_room.clear()
        self._waiters.clear()


#: Process-wide store — filters publish, ``await`` and the status route read.
verdicts = VerdictStore()


# ── Installing a filter ──────────────────────────────────────────────────────


def install(room: str, owner: str, fn: SummonFilter) -> None:
    """Install ``owner``'s summon filter in ``room``.

    An engine installs through here rather than through the bus directly, so the
    cache invalidation below can never be forgotten at a call site: registering a
    filter is an effect on how the room decides, and every cached decision made
    without it is stale the moment it lands.
    """
    lifecycle.install(room, SUMMON_FILTER, owner, fn)
    verdicts.forget_room(room)


def uninstall(room: str, owner: str) -> None:
    """Remove ``owner``'s summon filter from ``room`` (no-op when absent)."""
    if owner not in lifecycle.owners(room, SUMMON_FILTER):
        return
    lifecycle.uninstall(room, SUMMON_FILTER, owner)
    verdicts.forget_room(room)


def owners(room: str) -> list[str]:
    """The engines that installed a summon filter in ``room``."""
    return lifecycle.owners(room, SUMMON_FILTER)


def guarded(room: str) -> bool:
    """True when some engine installed a summon filter in ``room``."""
    return bool(lifecycle.hooks(room, SUMMON_FILTER))


# ── The two calls the room's summon path makes ───────────────────────────────


def _merge(handle_verdicts: list[str]) -> str:
    """One handle's answer across every filter that had an opinion.

    ``wake`` beats ``mention``; anything else — an abstention, or a verdict this
    version does not know — is not an opinion and carries no weight. No opinions
    at all means the default: wake.
    """
    opinions = [v for v in handle_verdicts if v in (WAKE, MENTION)]
    if not opinions:
        return WAKE
    return MENTION if all(v == MENTION for v in opinions) else WAKE


async def decide(ctx: SummonContext) -> dict[str, str]:
    """Run ``ctx`` through every summon filter installed in its room.

    With none installed every handle wakes — the room's behaviour before any
    guard existed, reached without touching an engine.
    """
    filters = lifecycle.hooks(ctx.room, SUMMON_FILTER)
    if not filters:
        return {norm(h): WAKE for h in ctx.handles}

    verdicts.begin(ctx.room, ctx.message_id)
    collected: dict[str, list[str]] = {norm(h): [] for h in ctx.handles}
    for fn in filters:
        try:
            result = await fn(ctx)
        except Exception:
            logger.exception("summon filter failed on room %s — failing the room open", ctx.room)
            return {norm(h): WAKE for h in ctx.handles}
        for handle, verdict in (result or {}).items():
            collected.setdefault(norm(handle), []).append(verdict)
    return {handle: _merge(answers) for handle, answers in collected.items()}


async def wakes(room: str, message_id: str, handle: str) -> bool:
    """Whether ``handle`` should be woken by ``message_id`` (the ``await`` gate).

    Waits out a judgement in flight — the long-poll has the time, and the
    alternative is serving a turn a filter was about to suppress. An unguarded
    room, an unjudged message, or a judgement that overruns the wait all answer
    ``True``.
    """
    if not guarded(room):
        return True
    verdict = await verdicts.wait(room, message_id, settings.SUMMON_FILTER_WAIT_S)
    if verdict is None:
        return True
    return verdict.wakes(handle)
