# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The status contract: what a provider is asked, and what it may answer.

A board row points at work that lives somewhere else — a pull request, a ticket,
a build.  Keeping that pointer live is the same problem for every tool, so the
app learns the problem once and knows none of the tools: a **provider** claims a
kind of reference and answers, in bulk, what state it is in.

Two shapes carry the whole design.

``Ref`` is the task.  Rows reference refs, not the other way round, so
two rows pointing at the same pull request cost one fetch between them.

``Liveness`` is a closed vocabulary plus an open bag.  ``state`` is one of six
words the board can colour and sort by without knowing what a "ticket" is;
``label`` is the provider's own phrasing, kept verbatim because "Needs review"
and "In QA" are the words the reader actually recognises.

The word *liveness*, and not *status*, is deliberate.  A board row already owns
``status`` for its own lifecycle (``open``, ``claimed``, ``in_progress`` …), a
different closed vocabulary that happens to share the word ``blocked`` with this
one meaning something else.  A provider answers about the *external* thing a row
points at, not the row's own lifecycle, so its answer lands on a row under a
separate field (``ROW_FIELD``) and is named for what it is here too, so the two
vocabularies can never quietly shadow one another in code.  The row field is
``upstream`` rather than ``live`` for the same reason: ``live`` is a boolean the
board already uses for agent presence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol, runtime_checkable

from app.services.status.auth import AuthScheme

#: What a surface can act on generically. A provider maps its own states onto
#: these; anything it cannot map is ``unknown`` rather than a guess.
#:
#: The six are pinned down here because two different readers infer different
#: things from the words alone, and a provider author mapping a tracker onto
#: them needs one answer:
#:
#: ``ok``       nothing is wrong and nobody is needed. Healthy, **not**
#:              finished — an approved pull request is ``ok`` until it merges.
#: ``pending``  in motion, nobody is required. Checks running, a first review
#:              not yet given, a draft.
#: ``blocked``  waiting on a person: a decision, a revision, an approval.
#: ``failed``   waiting on a fix, and a machine is what said no.
#: ``done``     terminal, however it ended. Merged, closed, cancelled — the
#:              distinction between a good and a bad ending is the ``label``'s
#:              to carry, not this field's.
#: ``unknown``  the provider met a state it cannot place. Honest ignorance,
#:              never a default for "no information".
#:
#: ``ok`` and ``done`` are the pair worth getting right: ``ok`` is a healthy
#: thing still in flight, ``done`` is a finished one.
LiveState = Literal["ok", "pending", "blocked", "failed", "done", "unknown"]

#: The board-row field a provider's answer lands under. Two names it cannot have:
#:
#: ``status`` is the row's own lifecycle (``open``, ``claimed``, ``in_progress``
#: …), a different closed vocabulary, and both contain ``blocked`` meaning
#: different things: a person has blocked the row, versus the external thing is
#: waiting on a person.
#:
#: ``live`` is already taken too, by a boolean the projections put on a row to
#: say an agent is resident on it. The board reads it as ``fields.live === true``
#: to light the presence dot beside an owner, and infers it as a ``checkbox``.
#: An object landed there would read as falsy presence and as the wrong field
#: type, which is the ``status`` collision again one field over.
#:
#: ``upstream`` is neither, and says what the value is: the answer from the tool
#: the row points at, upstream of this room.
ROW_FIELD: Final = "upstream"

#: How much the caller should trust what they were handed. This travels with
#: every value: an agent reasoning on a three-hour-old "CI green" is the failure
#: this design exists to prevent.
Freshness = Literal["fresh", "stale", "missing", "error"]


@dataclass(frozen=True, slots=True)
class Ref:
    """One external thing worth watching.

    Frozen and hashable because it is a cache key, a dedupe key, and the task
    the runtime batches by.
    """

    provider: str
    kind: str
    id: str
    url: str | None = None

    def __str__(self) -> str:
        return f"{self.provider}:{self.kind}:{self.id}"


@dataclass(frozen=True, slots=True)
class Liveness:
    """A provider's reading of an external thing: one of six states, plus its
    own words for it. Lands on a board row under ``ROW_FIELD``, never ``status``
    and never ``live`` (both are the row's own, meaning something else).
    """

    state: LiveState
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
    liveness: Liveness
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
    liveness: Liveness | None = None
    fetched_at: datetime | None = None
    error: str | None = None

    def age(self, now: datetime) -> timedelta | None:
        return None if self.fetched_at is None else now - self.fetched_at


@runtime_checkable
class Context(Protocol):
    """What a provider is handed. Deliberately small.

    ``http`` is pre-built against the provider's declared ``base_url`` with its
    credential, timeout and retry policy already applied, so a provider author
    writes request-and-parse and never auth or backoff.

    There is no way to read the credential's value.  A provider names what it
    needs and is handed a transport that already carries it, which means a
    provider cannot reach a host it never declared, and cannot send a token
    somewhere it wasn't meant to go.  The default implementation
    (``status.context.HttpContext``) enforces the host bound, not by convention:
    a request to any host other than ``base_url``'s is refused by the transport
    before it leaves the process, so a leaked token cannot follow a redirect or
    a hand-written absolute URL to somewhere it wasn't meant for.
    """

    @property
    def http(self) -> Any: ...

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

    #: The one host this provider talks to. ``ctx.http`` is bound to it.
    base_url: str

    #: How this provider's credential is presented, declared rather than read.
    #: An ``AuthScheme`` (``Bearer``, ``Basic``, ``Header``) names the credential
    #: name(s) it needs and how they render onto the wire; the runtime resolves
    #: the name(s) and builds the transport, so the value never reaches the
    #: provider. A provider that declares a scheme is never called at all while
    #: any of its credentials are missing, so a misconfigured integration reports
    #: itself instead of answering "unknown" for every row. ``None`` is genuinely
    #: no auth, distinct from a raw token under ``Authorization`` (``Header``).
    auth: AuthScheme | None

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
