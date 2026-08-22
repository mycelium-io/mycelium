# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Batches refs into provider calls, and decides what may be served.

Three entry points, because three callers want different bargains:

``read`` is the board's. It answers from cache and returns immediately, leaving
refreshes to the caller to schedule. A render never waits on GitHub.

``refresh`` is the sweeper's. It groups refs by provider, chunks each group to
that provider's batch size, and runs a bounded number of chunks at once — the
whole reason a provider exposes no single-ref call.

``resolve`` is for a caller that would rather wait than be told "unknown": a
refresh button, or an agent that has just pushed and wants the truth. It is the
only path that blocks, and it is bounded.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta

from app.services.status.cache import StatusCache
from app.services.status.types import Context, Err, Known, Ok, Ref, StatusProvider

#: How many provider chunks may be in the air at once, across all providers.
DEFAULT_CONCURRENCY = 4


class StatusRuntime:
    def __init__(
        self,
        providers: dict[str, StatusProvider],
        context: Context,
        cache: StatusCache | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        credentials: Mapping[str, str] | None = None,
    ) -> None:
        self._providers = providers
        self._context = context
        self._cache = cache or StatusCache()
        self._gate = asyncio.Semaphore(concurrency)
        self._credentials = credentials or {}

    def _missing_credential(self, provider: StatusProvider) -> str | None:
        name = getattr(provider, "credential", None)
        return name if name and not self._credentials.get(name) else None

    @property
    def cache(self) -> StatusCache:
        return self._cache

    # ── the read path ────────────────────────────────────────────────────────

    def read(
        self, refs: list[Ref], now: datetime, max_age: timedelta | None = None
    ) -> dict[Ref, Known]:
        """What we know, right now, without fetching anything.

        ``max_age`` is how a caller states its own tolerance instead of
        inheriting the provider's. A human reading "4m ago" can judge for
        themselves; an agent about to act on the answer usually cannot, so it
        passes a bound and is told ``missing`` rather than handed something too
        old to be evidence.
        """
        answers: dict[Ref, Known] = {}
        for ref in refs:
            provider = self._providers.get(ref.provider)
            if provider is None:
                answers[ref] = Known(
                    ref=ref, freshness="missing", error=f"no provider {ref.provider!r}"
                )
                continue
            known = self._cache.known(ref, now, provider.ttl, provider.swr)
            if max_age is not None and known.status is not None:
                age = known.age(now)
                if age is not None and age > max_age:
                    known = Known(ref=ref, freshness="missing", error=f"older than {max_age}")
            answers[ref] = known
        return answers

    def due(self, refs: list[Ref], now: datetime) -> list[Ref]:
        """The subset worth refreshing: not fresh, not in flight, not backing off."""
        due: list[Ref] = []
        for ref in refs:
            provider = self._providers.get(ref.provider)
            if provider is None or self._cache.in_flight(ref) or self._cache.backing_off(ref, now):
                continue
            if self._cache.classify(ref, now, provider.ttl, provider.swr) != "fresh":
                due.append(ref)
        return due

    # ── the fetch path ───────────────────────────────────────────────────────

    async def refresh(self, refs: list[Ref], now: datetime) -> None:
        """Fetch what is due, in as few provider calls as the batch sizes allow."""
        wanted = self.due(refs, now)
        mine, waits = self._cache.begin(wanted)

        by_provider: dict[str, list[Ref]] = defaultdict(list)
        for ref in mine:
            by_provider[ref.provider].append(ref)

        chunks: list[tuple[StatusProvider, list[Ref]]] = []
        for name, group in by_provider.items():
            provider = self._providers[name]
            size = max(1, provider.max_batch)
            chunks.extend((provider, group[i : i + size]) for i in range(0, len(group), size))

        await asyncio.gather(*(self._run_chunk(p, c, now) for p, c in chunks))
        if waits:
            await asyncio.gather(*waits)

    async def resolve(
        self, refs: list[Ref], now: datetime, max_age: timedelta | None = None
    ) -> dict[Ref, Known]:
        """Refresh, then answer. The blocking path."""
        await self.refresh(refs, now)
        return self.read(refs, now, max_age=max_age)

    async def _run_chunk(self, provider: StatusProvider, chunk: list[Ref], now: datetime) -> None:
        missing = self._missing_credential(provider)
        if missing is not None:
            # Refusing here rather than inside the provider keeps every provider
            # free of credential handling, and keeps a misconfigured one from
            # spending a request to discover it has no token.
            for ref in chunk:
                self._cache.put_err(ref, f"{provider.name}: {missing} not configured", now)
            self._cache.finish(chunk)
            return

        async with self._gate:
            try:
                outcomes = await provider.fetch(list(chunk), self._context)
            except Exception as exc:
                # A provider bug must not sink the sweep. Which refs in the chunk
                # survived is unknowable from here, so all are marked errored
                # rather than half-trusted.
                for ref in chunk:
                    self._cache.put_err(ref, f"{provider.name} raised: {exc}", now)
                self._cache.finish(chunk)
                return

            answered = set()
            for outcome in outcomes:
                answered.add(outcome.ref)
                if isinstance(outcome, Ok):
                    self._cache.put_ok(outcome.ref, outcome.status, now, ttl_override=outcome.ttl)
                elif isinstance(outcome, Err):
                    self._cache.put_err(
                        outcome.ref, outcome.reason, now, retry_after=outcome.retry_after
                    )

            # A provider that quietly drops a ref would otherwise leave it
            # looking un-fetched forever, retried on every sweep.
            for ref in chunk:
                if ref not in answered:
                    self._cache.put_err(ref, f"{provider.name} returned no outcome", now)

            self._cache.finish(chunk)

    # ── parsing ──────────────────────────────────────────────────────────────

    def claims(self, text: str) -> list[Ref]:
        """Every ref any registered provider recognises in a piece of text.

        This is the whole of the app's knowledge of external syntax: none. A
        pasted link becomes tracked work because a provider claimed it.
        """
        found: list[Ref] = []
        seen: set[Ref] = set()
        for provider in self._providers.values():
            for ref in provider.claims(text):
                if ref not in seen:
                    seen.add(ref)
                    found.append(ref)
        return found
