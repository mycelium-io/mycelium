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

from app.services.status.types import Freshness, Known, Ref, Status


@dataclass(slots=True)
class Entry:
    ref: Ref
    fetched_at: datetime
    status: Status | None = None
    error: str | None = None
    #: A provider may extend its own answer's life (a merged PR stops moving).
    ttl_override: timedelta | None = None
    #: Honoured before any refresh, so a rate-limited provider is left alone.
    retry_after: datetime | None = None


class StatusCache:
    """Per-ref entries plus single-flight.

    Single-flight is not an optimisation here, it is correctness of a sort: a
    room with twenty panels open would otherwise turn one stale pull request
    into twenty identical requests the instant it expires.
    """

    def __init__(self) -> None:
        self._entries: dict[Ref, Entry] = {}
        self._inflight: dict[Ref, asyncio.Future[None]] = {}

    # ── reads ────────────────────────────────────────────────────────────────

    def classify(self, ref: Ref, now: datetime, ttl: timedelta, swr: timedelta) -> Freshness:
        entry = self._entries.get(ref)
        if entry is None:
            return "missing"
        age = now - entry.fetched_at
        if entry.error is not None:
            # An error is remembered so a broken ref doesn't retry every render,
            # but it is never dressed up as a value.
            return "error" if age < ttl else "missing"
        if age < (entry.ttl_override or ttl):
            return "fresh"
        return "stale" if age < (entry.ttl_override or ttl) + swr else "missing"

    def known(self, ref: Ref, now: datetime, ttl: timedelta, swr: timedelta) -> Known:
        freshness = self.classify(ref, now, ttl, swr)
        entry = self._entries.get(ref)
        if entry is None or freshness == "missing":
            return Known(ref=ref, freshness="missing")
        return Known(
            ref=ref,
            freshness=freshness,
            status=entry.status,
            fetched_at=entry.fetched_at,
            error=entry.error,
        )

    # ── writes ───────────────────────────────────────────────────────────────

    def put_ok(
        self, ref: Ref, status: Status, now: datetime, ttl_override: timedelta | None = None
    ) -> None:
        self._entries[ref] = Entry(
            ref=ref, fetched_at=now, status=status, ttl_override=ttl_override
        )

    def put_err(
        self, ref: Ref, reason: str, now: datetime, retry_after: timedelta | None = None
    ) -> None:
        previous = self._entries.get(ref)
        self._entries[ref] = Entry(
            ref=ref,
            fetched_at=now,
            # A failed refresh must not erase the last thing that worked; it
            # ages out on its own schedule instead.
            status=previous.status if previous else None,
            error=reason,
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
