# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
A faceted query language, and the engine that runs one over a set of documents.

One line of text carries the words to look for and every field to narrow by::

    from:avery task:checkout after:2d "apple pay" -stance:reject sort:oldest

Tokens
------
``word``              free text; every word must appear (case-insensitive).
``"a phrase"``        an exact phrase that must appear.
``-word``             a word that must not appear.
``field:value``       keep documents whose ``field`` matches ``value``. The same
                      field given twice is an OR (``from:a from:b``); different
                      fields AND together. ``field:"two words"`` quotes a value.
``-field:value``      drop documents whose ``field`` matches ``value``.
``after:`` ``before:`` ``on:``
                      time bounds. A value is an ISO date or stamp, an age
                      (``30m``, ``2h``, ``3d``, ``1w``), ``today`` or
                      ``yesterday``. ``on:`` is the whole UTC day.
``sort:``             ``newest`` (default), ``oldest`` or ``relevance``.

A ``field:`` the caller did not declare is free text, so a URL or a memory key
with a colon in it still searches as written. A value that cannot be read (a
date that isn't one, a sort that doesn't exist) is not silently dropped: it is
reported in :attr:`FacetQuery.problems`, and the response echoes it so the
person or agent who typed it finds out.

Nothing here knows what a document is. A caller declares its fields as
:class:`Field` extractors (what values a document has for that field, and how a
typed value matches one) and gets back the matching documents with a count per
value for every field. Messages are the first caller; memories can be the next
without a second grammar.

Facet counts are *disjunctive*: a field's counts are taken over the documents
that pass every other clause but not that field's own, so after ``from:avery``
the sender facet still lists everyone else and what choosing them would give,
rather than collapsing to a single bucket.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

D = TypeVar("D")

SORTS: tuple[str, ...] = ("newest", "oldest", "relevance")

#: The time keywords and the bound each one sets.
_TIME_KEYS: dict[str, str] = {
    "after": "after",
    "since": "after",
    "before": "before",
    "until": "before",
    "on": "on",
}

_AGE = re.compile(r"^(\d+)\s*(m|min|h|d|w)$", re.IGNORECASE)
_AGE_UNITS = {"m": "minutes", "min": "minutes", "h": "hours", "d": "days", "w": "weeks"}

# One token: an optional leading ``-``, then either ``name:value`` (value may be
# quoted) or a bare/quoted word. ``@handle`` is passed through as a word and
# mapped by the caller's declared shorthand.
_TOKEN = re.compile(r'(-?)(?:([A-Za-z][\w-]*):)?("([^"]*)"?|\S+)')


@dataclass(frozen=True)
class Clause:
    """One ``field:value`` the query narrows by."""

    field: str
    value: str
    negate: bool = False


@dataclass(frozen=True)
class FacetQuery:
    """A raw query, split into what to match and how to order it."""

    #: Words every hit must contain, lowercased.
    terms: tuple[str, ...] = ()
    #: Exact phrases every hit must contain, lowercased.
    phrases: tuple[str, ...] = ()
    #: Words no hit may contain, lowercased.
    excluded: tuple[str, ...] = ()
    clauses: tuple[Clause, ...] = ()
    after: datetime | None = None
    before: datetime | None = None
    sort: str = "newest"
    #: Tokens that looked like scope but could not be read, as typed.
    problems: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        """The free text as one string (words and phrases), for display."""
        return " ".join([*self.terms, *(f'"{p}"' for p in self.phrases)])

    @property
    def needles(self) -> tuple[str, ...]:
        """Everything a hit was matched on, for highlighting a snippet."""
        return (*self.phrases, *self.terms)


def parse_time(raw: str, *, now: datetime | None = None, end: bool = False) -> datetime | None:
    """A point in time as typed: an age, ``today``/``yesterday``, or ISO 8601.

    A bare date is the start of that UTC day, or with ``end`` the start of the
    next one, so ``before:2026-09-03`` excludes the 3rd and ``on:`` spans it.
    """
    now = now or datetime.now(UTC)
    text = raw.strip().lower()
    match = _AGE.match(text)
    if match:
        return now - timedelta(**{_AGE_UNITS[match.group(2)]: int(match.group(1))})
    if text in ("today", "yesterday"):
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if text == "yesterday":
            day -= timedelta(days=1)
        return day + timedelta(days=1) if end else day
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    is_date = len(raw.strip()) == 10
    return stamp + timedelta(days=1) if end and is_date else stamp


def parse(
    raw: str,
    fields: Iterable[str],
    *,
    aliases: dict[str, str] | None = None,
    at_field: str | None = None,
    now: datetime | None = None,
) -> FacetQuery:
    """Split ``raw`` into terms, phrases and clauses over the declared ``fields``.

    ``aliases`` maps extra spellings onto a field (``sender`` → ``from``), and
    ``at_field`` names the field ``@handle`` is shorthand for.
    """
    known = set(fields)
    alias = {**{f: f for f in known}, **(aliases or {})}
    terms: list[str] = []
    phrases: list[str] = []
    excluded: list[str] = []
    clauses: list[Clause] = []
    problems: list[str] = []
    after: datetime | None = None
    before: datetime | None = None
    sort = "newest"

    for m in _TOKEN.finditer(raw or ""):
        negate = m.group(1) == "-"
        name = (m.group(2) or "").lower()
        quoted = m.group(4)
        value = quoted if quoted is not None else m.group(3)
        token = m.group(0)

        if name and name in _TIME_KEYS:
            bound = _TIME_KEYS[name]
            start = parse_time(value, now=now)
            stop = parse_time(value, now=now, end=True)
            if start is None or stop is None or negate:
                problems.append(token)
            elif bound == "after":
                after = start if after is None else max(after, start)
            elif bound == "before":
                # Exclusive at the start: ``before:2026-09-03`` stops at that day.
                before = start if before is None else min(before, start)
            else:
                after = start if after is None else max(after, start)
                before = stop if before is None else min(before, stop)
            continue
        if name == "sort":
            if value.lower() in SORTS and not negate:
                sort = value.lower()
            else:
                problems.append(token)
            continue
        if name and name in alias:
            if value:
                clauses.append(Clause(alias[name], value, negate))
            continue
        if name:
            # Not a field we know: the whole token is text, colon and all.
            value = f"{m.group(2)}:{value}"
        elif at_field and value.startswith("@") and len(value) > 1 and quoted is None:
            clauses.append(Clause(at_field, value[1:], negate))
            continue

        word = value.lower().strip()
        if not word:
            continue
        # ``from:`` with nothing after it yet: a field still being typed narrows
        # nothing, rather than asking every hit to contain the text "from:".
        bare = word[:-1]
        if word.endswith(":") and (bare in alias or bare in _TIME_KEYS or bare == "sort"):
            continue
        if negate:
            excluded.append(word)
        elif quoted is not None and not name:
            phrases.append(" ".join(word.split()))
        else:
            terms.append(word)

    return FacetQuery(
        terms=tuple(terms),
        phrases=tuple(phrases),
        excluded=tuple(excluded),
        clauses=tuple(clauses),
        after=after,
        before=before,
        sort=sort,
        problems=tuple(problems),
    )


# ── the engine ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Field(Generic[D]):
    """One facet a caller can filter by and count.

    ``values`` returns the values a document has for the field (none, one or
    many). ``matches`` decides whether one of them satisfies what was typed;
    the default is a case-insensitive equality. ``label`` turns a value into
    what a person reads in a facet list, when the value itself is an id.
    ``facet`` false makes a field filterable but uncounted (a free-form value
    like a URL, where a bucket per value tells nobody anything).
    """

    name: str
    values: Callable[[D], Iterable[str]]
    matches: Callable[[str, str], bool] = field(
        default=lambda typed, value: typed.lower() == value.lower()
    )
    label: Callable[[str], str] | None = None
    facet: bool = True


@dataclass(frozen=True)
class Bucket:
    value: str
    label: str
    count: int


@dataclass
class Outcome(Generic[D]):
    """Every document that matched, scored, plus the facet counts."""

    hits: list[tuple[D, float]]
    facets: dict[str, list[Bucket]]
    scanned: int


def _text_score(text: str, query: FacetQuery) -> float | None:
    """How well ``text`` answers the free text; ``None`` when it fails to."""
    lowered = text.lower()
    if any(x in lowered for x in query.excluded):
        return None
    score = 0.0
    for phrase in query.phrases:
        n = lowered.count(phrase)
        if n == 0:
            return None
        score += 3.0 * n
    for term in query.terms:
        n = lowered.count(term)
        if n == 0:
            return None
        # A whole-word hit reads as a better answer than a fragment of one.
        whole = len(re.findall(rf"(?<!\w){re.escape(term)}(?!\w)", lowered))
        score += min(n, 5) + whole
    return score


def run(
    docs: Sequence[D],
    query: FacetQuery,
    fields: Sequence[Field[D]],
    *,
    text: Callable[[D], str],
    when: Callable[[D], datetime],
    facet_limit: int = 12,
) -> Outcome[D]:
    """Filter ``docs`` by ``query`` and count each field's values.

    Hits come back in the query's sort order; relevance ties break newest-first.
    """
    by_name = {f.name: f for f in fields}
    grouped: dict[str, list[Clause]] = {}
    for clause in query.clauses:
        if clause.field in by_name:
            grouped.setdefault(clause.field, []).append(clause)

    def passes(doc_values: list[str], clauses: list[Clause], spec: Field[D]) -> bool:
        wanted = [c for c in clauses if not c.negate]
        refused = [c for c in clauses if c.negate]
        if any(spec.matches(c.value, v) for c in refused for v in doc_values):
            return False
        return not wanted or any(spec.matches(c.value, v) for c in wanted for v in doc_values)

    counted = [f for f in fields if f.facet]
    counters: dict[str, Counter[str]] = {f.name: Counter() for f in counted}
    hits: list[tuple[D, float]] = []

    for doc in docs:
        at = when(doc)
        if query.after is not None and at < query.after:
            continue
        if query.before is not None and at >= query.before:
            continue
        score = _text_score(text(doc), query)
        if score is None:
            continue
        values = {f.name: list(f.values(doc)) for f in fields}
        failed = [
            name for name, cs in grouped.items() if not passes(values[name], cs, by_name[name])
        ]
        if len(failed) > 1:
            continue
        # Disjunctive counts: a field is counted over documents that pass
        # everything but itself, so its other values stay visible as choices.
        for spec in counted:
            if not failed or failed == [spec.name]:
                counters[spec.name].update(set(values[spec.name]))
        if not failed:
            hits.append((doc, score))

    if query.sort == "oldest":
        hits.sort(key=lambda h: when(h[0]))
    elif query.sort == "relevance":
        hits.sort(key=lambda h: (h[1], when(h[0])), reverse=True)
    else:
        hits.sort(key=lambda h: when(h[0]), reverse=True)

    facets: dict[str, list[Bucket]] = {}
    for spec in counted:
        top = counters[spec.name].most_common(facet_limit)
        if top:
            facets[spec.name] = [
                Bucket(value=v, label=spec.label(v) if spec.label else v, count=n) for v, n in top
            ]
    return Outcome(hits=hits, facets=facets, scanned=len(docs))


def snippet(text: str, needles: Sequence[str], *, width: int = 180) -> str:
    """A one-line window of ``text`` centered on the first needle in it."""
    flat = " ".join(text.split())
    if len(flat) <= width:
        return flat
    lowered = flat.lower()
    at = next((i for i in (lowered.find(n) for n in needles if n) if i >= 0), -1)
    if at < 0:
        return flat[:width].rstrip() + "…"
    start = max(0, at - width // 3)
    window = flat[start : start + width].strip()
    return ("…" if start > 0 else "") + window + ("…" if start + width < len(flat) else "")
