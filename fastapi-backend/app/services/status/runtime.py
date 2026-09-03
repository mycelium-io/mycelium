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

from app.services.status.auth import AuthScheme
from app.services.status.cache import StatusCache
from app.services.status.context import ProviderContextFactory, build_http_context
from app.services.status.types import (
    CachedStatus,
    FetchFailed,
    FetchSucceeded,
    ProviderContext,
    Ref,
    StatusProvider,
)

#: How many provider chunks may be in the air at once, across all providers.
DEFAULT_CONCURRENCY = 4


class ProviderConformanceError(ValueError):
    """A provider whose ``auth`` declaration is malformed, refused at registration.

    ``StatusProvider`` is a structural ``Protocol``, so nothing forces a provider
    to declare ``auth`` at all, nor to declare it as an ``AuthScheme``. Two ways
    to get it wrong both fail worse than loudly:

    * a provider that *forgets* ``auth`` reads as ``None`` (no auth) and goes
      silently unauthenticated;
    * a provider that declares ``auth`` in the wrong shape (the pre-scheme
      ``auth = "GITHUB_TOKEN"`` string, say) raises ``AttributeError`` deep in
      the sweep, in ``_missing_credential`` which runs *outside* ``_run_chunk``'s
      ``try``, so the exception propagates through ``refresh``'s ``gather`` and
      sinks every provider's chunk, not just the offender's.

    Catching it here, at construction, converts both into a clear error naming
    the provider before a single ref is fetched.
    """


def _check_conformance(providers: dict[str, StatusProvider]) -> None:
    """Refuse any provider whose ``auth`` is missing or not an ``AuthScheme``.

    Registration is the one choke point every provider passes through, and the
    check is cheap because ``AuthScheme`` is ``runtime_checkable``. Validating
    here rather than defensively on every sweep means the invariant "every
    provider in ``self._providers`` has a well-formed ``auth``" holds for the
    whole life of the runtime, so the hot path never re-checks it.
    """
    for name, provider in providers.items():
        if not hasattr(provider, "auth"):
            raise ProviderConformanceError(
                f"provider {name!r} declares no 'auth'; write 'auth = None' to mean no "
                "authentication, so the absence is a decision rather than an oversight"
            )
        auth = provider.auth
        if auth is not None and not isinstance(auth, AuthScheme):
            raise ProviderConformanceError(
                f"provider {name!r} has auth={auth!r}, which is not an AuthScheme "
                "(expected Bearer, Basic, Header, or None)"
            )


class StatusRuntime:
    """Owns one bound ``ProviderContext`` per provider, built on first use.

    The context is per provider, not one shared instance, because the protocol
    binds ``ctx.http`` to *each* provider's own ``base_url`` and credential: a
    single shared transport cannot be two hosts at once. The runtime resolves the
    credential (from ``credentials``) and the factory binds it into a transport,
    so the value crosses from here to the wire without any provider touching it.
    """

    def __init__(
        self,
        providers: dict[str, StatusProvider],
        context_factory: ProviderContextFactory | None = None,
        cache: StatusCache | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        credentials: Mapping[str, str] | None = None,
    ) -> None:
        _check_conformance(providers)
        self._providers = providers
        self._context_factory = context_factory or build_http_context
        self._contexts: dict[str, ProviderContext] = {}
        self._cache = cache or StatusCache()
        self._gate = asyncio.Semaphore(concurrency)
        self._credentials = credentials or {}

    def _missing_credential(self, provider: StatusProvider) -> str | None:
        """Why a provider cannot be called for want of a credential, or ``None``.

        A scheme may need more than one name (``Basic`` needs an identity and a
        secret), so "configured" is all-of, not any-of: a Jira provider with the
        email set but the token missing is still refused. The reason goes straight
        into the caller's error, and it names not just *which* value is absent but
        *how*: a name the resolver never saw is ``not configured``, while a name
        present with an empty value is ``set but empty``. Both are unusable, but an
        operator fixes them differently, so the distinction the resolver preserves
        (absent from the mapping versus present as ``""``) is carried through here
        rather than collapsed back into a single "missing".
        """
        auth = getattr(provider, "auth", None)
        if auth is None:
            return None
        problems: list[str] = []
        for name in auth.names():
            if name not in self._credentials:
                problems.append(f"{name} not configured")
            elif not self._credentials[name]:
                problems.append(f"{name} set but empty")
        return ", ".join(problems) if problems else None

    def _context_for(self, provider: StatusProvider) -> ProviderContext:
        """The provider's bound context, built once and reused.

        Built only after the credential check has passed, so every name the
        scheme declares resolves to a real value here, never the empty string a
        missing credential would resolve to. The scheme renders the resolved
        values into headers; the factory only binds them.
        """
        ctx = self._contexts.get(provider.name)
        if ctx is None:
            auth = getattr(provider, "auth", None)
            rendered = (
                auth.headers({name: self._credentials[name] for name in auth.names()})
                if auth
                else None
            )
            ctx = self._context_factory(provider, rendered)
            self._contexts[provider.name] = ctx
        return ctx

    async def aclose(self) -> None:
        """Close every built context. The transports own sockets; the runtime owns
        the transports, so releasing them is the runtime's to do."""
        for ctx in self._contexts.values():
            closer = getattr(ctx, "aclose", None)
            if closer is not None:
                await closer()
        self._contexts.clear()

    @property
    def cache(self) -> StatusCache:
        return self._cache

    # ── the read path ────────────────────────────────────────────────────────

    def read(
        self, refs: list[Ref], now: datetime, max_age: timedelta | None = None
    ) -> dict[Ref, CachedStatus]:
        """What we know, right now, without fetching anything.

        ``max_age`` is how a caller states its own tolerance instead of
        inheriting the provider's. A human reading "4m ago" can judge for
        themselves; an agent about to act on the answer usually cannot, so it
        passes a bound and is told ``missing`` rather than handed something too
        old to be evidence.
        """
        answers: dict[Ref, CachedStatus] = {}
        for ref in refs:
            provider = self._providers.get(ref.provider)
            if provider is None:
                answers[ref] = CachedStatus(
                    ref=ref, freshness="missing", error=f"no provider {ref.provider!r}"
                )
                continue
            cached = self._cache.lookup(ref, now, provider.ttl, provider.swr)
            if max_age is not None and cached.upstream is not None:
                age = cached.age(now)
                if age is not None and age > max_age:
                    cached = CachedStatus(
                        ref=ref, freshness="missing", error=f"older than {max_age}"
                    )
            answers[ref] = cached
        return answers

    def due(self, refs: list[Ref], now: datetime) -> list[Ref]:
        """The subset worth refreshing: not fresh, not backing off.

        Deliberately *not* filtered by what is already in flight. That is
        ``StatusCache.begin``'s job, and it can do something this cannot: hand
        back the future to wait on, so a second caller joins the fetch already
        running instead of being told the ref is missing. Filtering here would
        make ``begin``'s waiting half unreachable and quietly turn ``resolve``,
        the documented blocking path, into one that does not block.
        """
        due: list[Ref] = []
        for ref in refs:
            provider = self._providers.get(ref.provider)
            if provider is None or self._cache.backing_off(ref, now):
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
    ) -> dict[Ref, CachedStatus]:
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
                self._cache.put_err(ref, f"{provider.name}: {missing}", now)
            self._cache.finish(chunk)
            return

        async with self._gate:
            # The claim must be released on every exit, including a cancellation:
            # a client that disconnects mid-``?refresh=true`` would otherwise
            # leave these refs claimed for the life of the process, and anything
            # waiting on them waiting forever.
            try:
                outcomes = await provider.fetch(list(chunk), self._context_for(provider))
            except Exception as exc:
                # A provider bug must not sink the sweep. Which refs in the chunk
                # survived is unknowable from here, so all are marked errored
                # rather than half-trusted.
                for ref in chunk:
                    self._cache.put_err(ref, f"{provider.name} raised: {exc}", now)
                return
            else:
                answered = set()
                for outcome in outcomes:
                    answered.add(outcome.ref)
                    if isinstance(outcome, FetchSucceeded):
                        self._cache.put_ok(
                            outcome.ref, outcome.upstream, now, ttl_override=outcome.ttl
                        )
                    elif isinstance(outcome, FetchFailed):
                        self._cache.put_err(
                            outcome.ref, outcome.reason, now, retry_after=outcome.retry_after
                        )

                # A provider that quietly drops a ref would otherwise leave it
                # looking un-fetched forever, retried on every sweep.
                for ref in chunk:
                    if ref not in answered:
                        self._cache.put_err(ref, f"{provider.name} returned no outcome", now)
            finally:
                self._cache.finish(chunk)

    # ── parsing ──────────────────────────────────────────────────────────────

    def claims(self, text: str) -> list[Ref]:
        """Every ref any registered provider recognizes in a piece of text.

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
