# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The status contract: what a provider is asked, and what it may answer.

A board row points at work that lives somewhere else — a pull request, a ticket,
a build.  Keeping that pointer live is the same problem for every tool, so the
app learns the problem once and knows none of the tools: a **provider** claims a
kind of reference and answers, in bulk, what state it is in.

Two shapes carry the whole design.

``Ref`` is the unit of work.  Rows reference refs, not the other way round, so
two rows pointing at the same pull request cost one fetch between them.

``Status`` is a closed vocabulary plus an open bag.  ``state`` is one of six
words the board can colour and sort by without knowing what a "ticket" is;
``label`` is the provider's own phrasing, kept verbatim because "Needs review"
and "In QA" are the words the reader actually recognises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, runtime_checkable

#: What the board can act on generically. A provider maps its own states onto
#: these; anything it cannot map is ``unknown`` rather than a guess.
State = Literal["ok", "pending", "blocked", "failed", "done", "unknown"]

#: How much the caller should trust what they were handed. This travels with
#: every value: an agent reasoning on a three-hour-old "CI green" is the failure
#: this design exists to prevent.
Freshness = Literal["fresh", "stale", "missing", "error"]


@dataclass(frozen=True, slots=True)
class Ref:
    """One external thing worth watching.

    Frozen and hashable because it is a cache key, a dedupe key, and the unit
    the runtime batches by.
    """

    provider: str
    kind: str
    id: str
    url: str | None = None

    def __str__(self) -> str:
        return f"{self.provider}:{self.kind}:{self.id}"


@dataclass(frozen=True, slots=True)
class Status:
    state: State
    #: The provider's own word for it, shown as-is.
    label: str
    url: str | None = None
    #: When the *source* last changed — not when we fetched it.
    source_updated_at: datetime | None = None
    #: Anything else the provider wants to carry. Never interpreted here.
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Ok:
    ref: Ref
    status: Status
    #: Override the provider's default freshness window for this one answer —
    #: a merged pull request can be cached far longer than an open one.
    ttl: timedelta | None = None


@dataclass(frozen=True, slots=True)
class Err:
    ref: Ref
    reason: str
    #: Honour a provider's rate-limit reply rather than hammering it.
    retry_after: timedelta | None = None


#: One outcome per ref. A batch where three refs 404 must still answer for the
#: other forty-seven, so failure is a value rather than an exception.
Outcome = Ok | Err


@dataclass(frozen=True, slots=True)
class Known:
    """What the app hands a caller: a value, and how much to trust it."""

    ref: Ref
    freshness: Freshness
    status: Status | None = None
    fetched_at: datetime | None = None
    error: str | None = None

    def age(self, now: datetime) -> timedelta | None:
        return None if self.fetched_at is None else now - self.fetched_at


@runtime_checkable
class Context(Protocol):
    """What a provider is handed. Deliberately small.

    ``http`` is pre-built with the provider's own credential, timeout and retry
    policy, so a provider author writes request-and-parse and never auth or
    backoff — and so a provider cannot quietly reach a host it never declared.
    """

    @property
    def http(self) -> Any: ...

    def secret(self, name: str) -> str | None: ...

    def log(self, message: str, **fields: Any) -> None: ...


@runtime_checkable
class StatusProvider(Protocol):
    """A provider claims a kind of reference and resolves it in bulk.

    There is deliberately **no single-ref fetch**. Offering one guarantees it
    gets called in a loop over a hundred rows, which is how an integration
    becomes a denial-of-service against the tool it integrates with. The runtime
    batches, chunks and bounds concurrency precisely because this is the only
    entry point.
    """

    #: Stable key. Matches the ``providers/{name}`` manifest in room memory.
    name: str

    #: Most refs the provider will accept in one call. The runtime chunks to it.
    max_batch: int

    #: How long an answer stays fresh, and how long past that it may still be
    #: served while a refresh runs behind it.
    ttl: timedelta
    swr: timedelta

    def claims(self, text: str) -> list[Ref]:
        """Refs this provider recognises in a piece of room text.

        This is why the app knows no syntax: ``#504`` means a pull request only
        because a provider said so.
        """
        ...

    async def fetch(self, refs: list[Ref], ctx: Context) -> list[Outcome]:
        """Resolve a chunk. One outcome per ref, in any order.

        Raising is a bug, not a protocol: the runtime catches it and marks every
        ref in the chunk errored, because it cannot know which ones survived.
        """
        ...
