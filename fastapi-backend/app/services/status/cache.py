# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Stale-while-revalidate for backend fetches.

The read path never waits on a network call.  A board render asks what it knows,
gets it, and leaves a refresh running behind it — the same bargain SWR makes in
a browser, for the same reason: a surface that blocks on someone else's API is a
surface people stop opening.

Two windows per entry.  Inside ``ttl`` a value is fresh and nothing is fetched.
Past ``ttl`` but inside ``swr`` it is served *and* refreshed, so the reader sees
the last known state with its age rather than a spinner.  Past ``swr`` it is no
longer evidence and is withheld.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.services.status.types import CachedStatus, Freshness, Ref, UpstreamState


@dataclass(slots=True)
class CacheEntry:
    ref: Ref
    #: When the *value* was obtained. A failed refresh never moves this: the age
    #: a caller is told is the age of the thing it is looking at, not the age of
    #: the most recent attempt to replace it.
    fetched_at: datetime
    upstream: UpstreamState | None = None
    error: str | None = None
    #: When the last attempt failed, kept apart from ``fetched_at`` because they
    #: answer different questions: how old is this value, and how recently did we
    #: try. Only the second should decide whether to try again.
    errored_at: datetime | None = None
    #: A provider may extend its own answer's life (a merged PR stops moving).
    ttl_override: timedelta | None = None
    #: Honored before any refresh, so a rate-limited provider is left alone.
    retry_after: datetime | None = None


class StatusCache:
    """Per-ref entries plus single-flight.

    Single-flight is not an optimization here, it is correctness of a sort: a
    room with twenty panels open would otherwise turn one stale pull request
    into twenty identical requests the instant it expires.
    """

    def __init__(self) -> None:
        self._entries: dict[Ref, CacheEntry] = {}
        self._inflight: dict[Ref, asyncio.Future[None]] = {}

    # ── reads ────────────────────────────────────────────────────────────────

    def classify(self, ref: Ref, now: datetime, ttl: timedelta, swr: timedelta) -> Freshness:
        entry = self._entries.get(ref)
        if entry is None:
            return "missing"
        age = now - entry.fetched_at
        window = (entry.ttl_override or ttl) + swr
        if entry.error is not None:
            if entry.upstream is None:
                # Nothing was ever cached. The error is the whole answer, and it
                # is worth remembering only as long as a value would have been,
                # so a broken ref does not retry on every render.
                since = now - (entry.errored_at or entry.fetched_at)
                return "error" if since < ttl else "missing"
            # A value we still hold, with a failed refresh behind it. It ages on
            # its own schedule, so it leaves evidence when it is genuinely too
            # old rather than being kept alive by the failures.
            return "error" if age < window else "missing"
        if age < (entry.ttl_override or ttl):
            return "fresh"
        return "stale" if age < window else "missing"

    def lookup(self, ref: Ref, now: datetime, ttl: timedelta, swr: timedelta) -> CachedStatus:
        freshness = self.classify(ref, now, ttl, swr)
        entry = self._entries.get(ref)
        if entry is None or freshness == "missing":
            return CachedStatus(ref=ref, freshness="missing")
        return CachedStatus(
            ref=ref,
            freshness=freshness,
            upstream=entry.upstream,
            fetched_at=entry.fetched_at,
            error=entry.error,
        )

    # ── writes ───────────────────────────────────────────────────────────────

    def put_ok(
        self,
        ref: Ref,
        upstream: UpstreamState,
        now: datetime,
        ttl_override: timedelta | None = None,
    ) -> None:
        self._entries[ref] = CacheEntry(
            ref=ref, fetched_at=now, upstream=upstream, ttl_override=ttl_override
        )

    def put_err(
        self, ref: Ref, reason: str, now: datetime, retry_after: timedelta | None = None
    ) -> None:
        previous = self._entries.get(ref)
        keep = previous.upstream if previous else None
        self._entries[ref] = CacheEntry(
            ref=ref,
            # A failed refresh must not erase the last thing that worked, and
            # must not make it look younger either: the retained value keeps the
            # time it was actually obtained, so its age stays true and a caller
            # asking for a bound on it is answered honestly. Stamping ``now``
            # here would hand an agent a three-hour-old "CI green" that satisfies
            # a five-minute freshness bound, which is the failure this whole
            # module exists to prevent.
            fetched_at=previous.fetched_at if previous and keep else now,
            upstream=keep,
            error=reason,
            errored_at=now,
            ttl_override=previous.ttl_override if previous and keep else None,
            retry_after=now + retry_after if retry_after else None,
        )

    def backing_off(self, ref: Ref, now: datetime) -> bool:
        entry = self._entries.get(ref)
        return bool(entry and entry.retry_after and now < entry.retry_after)

    def touch(self, ref: Ref, now: datetime) -> None:
        """Extend a fresh entry without refetching (an unchanged ETag)."""
        entry = self._entries.get(ref)
        if entry is not None:
            self._entries[ref] = replace(entry, fetched_at=now)

    # ── single-flight ────────────────────────────────────────────────────────

    def begin(self, refs: list[Ref]) -> tuple[list[Ref], list[asyncio.Future[None]]]:
        """Claim refs for fetching; return the ones to fetch and what to await.

        Refs already in flight are not fetched again — the caller awaits the
        existing attempt instead.
        """
        mine: list[Ref] = []
        waits: list[asyncio.Future[None]] = []
        for ref in refs:
            existing = self._inflight.get(ref)
            if existing is not None:
                waits.append(existing)
                continue
            self._inflight[ref] = asyncio.get_event_loop().create_future()
            mine.append(ref)
        return mine, waits

    def finish(self, refs: list[Ref]) -> None:
        for ref in refs:
            future = self._inflight.pop(ref, None)
            if future is not None and not future.done():
                future.set_result(None)

    def in_flight(self, ref: Ref) -> bool:
        return ref in self._inflight
