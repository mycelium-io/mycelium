# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Deep search over one room's messages: every message, every field, with facets.

``/api/search`` is the palette's typeahead: it ranks every entity type at once,
so it reads only a room's newest messages and keeps a handful of each kind.
This is the other job — finding the thing someone said, anywhere in a room's
history, by who said it, when, in which task, to whom, and how it landed — and
it answers with counts per field so a caller (most often an agent) can narrow
step by step rather than guess at filters.

The grammar is :mod:`app.services.facet_query`'s; this module declares the
fields a message has:

=============  ================================================================
``from:``      who said it (``@handle`` is shorthand; ``sender:``, ``by:``)
``to:``        who it was addressed to: a direct recipient or an L9 recipient
``mentions:``  who it ``@``-mentions in its text
``type:``      message type (``broadcast``, ``direct``, ``announce`` …)
``kind:``      an event's kind, or the L9 subkind it rode (``amend`` …)
``status:``    an event's ledger status
``task:``      the board row whose thread it was said in, by key or title
``thread:``    the episode URN, or its short id
``in:``        ``channel`` (said in the room) or ``thread`` (inside a task)
``stance:``    ``accept`` / ``reject`` as the message stated it
``step:``      the conductor step it belongs to
``is:``        ``edited``, ``conductor``
``has:``       ``mention``, ``link``, ``memory``, ``code``, ``scores``
``day:``       the UTC day it was said (``2026-09-03``)
=============  ================================================================

By default the search covers what was *said* (the prose message types); the
structured frames the feed also carries (``l9_*``, coordination lifecycle)
hold serialized envelopes rather than text, so they come in only when a
``type:`` names them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.schemas import PROSE_MESSAGE_TYPES
from app.services import facet_query, l9, markers, persister
from app.services.facet_query import FacetQuery, Field

if TYPE_CHECKING:
    from app.services.in_memory_store import StoredMessage

#: The fields this module declares, in the order a caller listing them shows them.
FIELDS: tuple[str, ...] = (
    "from",
    "to",
    "mentions",
    "task",
    "in",
    "type",
    "kind",
    "status",
    "stance",
    "step",
    "is",
    "has",
    "day",
    "thread",
)

ALIASES: dict[str, str] = {
    "sender": "from",
    "by": "from",
    "author": "from",
    "recipient": "to",
    "mention": "mentions",
    "row": "task",
    "episode": "thread",
    "date": "day",
}

#: The fields whose values are a closed set, and that set. ``contracts/
#: message-search.json`` freezes these so the CLI's copy, and every query
#: written in the docs and prompts, can be checked against them.
CLOSED_VALUES: dict[str, tuple[str, ...]] = {
    "in": ("channel", "thread"),
    "is": ("edited", "conductor"),
    "has": ("mention", "link", "memory", "code", "scores"),
    "stance": ("accept", "reject"),
}

_LINK = re.compile(r"https?://\S+")
_MEMORY_LINK = re.compile(r"\[\[[^\]]+\]\]|myc://\S+")


@dataclass(frozen=True)
class Side:
    """What the transcript knows about a message that the chat row dropped."""

    recipients: tuple[str, ...] = ()
    stance: str | None = None
    subkind: str | None = None
    scored: bool = False


@dataclass
class Doc:
    """A message with every field it will be searched by worked out once."""

    message: StoredMessage
    side: Side
    mentions: tuple[str, ...]
    task: str | None
    thread: str | None


@dataclass
class Hit:
    doc: Doc
    score: float
    snippet: str
    before: list[StoredMessage]
    after: list[StoredMessage]


@dataclass
class Result:
    query: FacetQuery
    hits: list[Hit]
    total: int
    facets: dict[str, list[facet_query.Bucket]]
    scanned: int
    next_cursor: str | None
    task_titles: dict[str, str]


# ── what the transcript knows ────────────────────────────────────────────────

_side_cache: dict[str, tuple[tuple[int, int], dict[str, Side]]] = {}


def _side_of(record: persister.TranscriptRecord) -> Side:
    header = (record.content.get("l9") or {}).get("header") or {}
    actors = ((header.get("participants") or {}).get("actors")) or []
    ids = [a.get("id") for a in actors if isinstance(a, dict) and isinstance(a.get("id"), str)]
    recipients = tuple(h for h in ids[1:] if h and h != l9.SYSTEM_ACTOR_ID)
    return Side(
        recipients=recipients,
        stance=markers.stance_of(record.content),
        subkind=record.subkind,
        scored=bool(markers.scores_of(record.content)),
    )


def transcript_sides(room: str) -> dict[str, Side]:
    """Recipients, stance and subkind per envelope id, re-read only on change."""
    from app.services.filesystem import get_room_dir

    path = get_room_dir(room) / persister.TRANSCRIPT_FILENAME
    stamp = persister._stat_stamp(path)
    if stamp is None:
        _side_cache.pop(room, None)
        return {}
    cached = _side_cache.get(room)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    sides = {r.message_id: _side_of(r) for r in persister.load_transcript(room) if r.message_id}
    _side_cache[room] = (stamp, sides)
    return sides


def thread_rows(room: str) -> dict[str, tuple[str, str]]:
    """``episode URN → (row key, title)`` for every board row with a thread."""
    from app.services.filesystem import EPISODE_META, get_room_dir, list_memory_files, system_meta

    rows: dict[str, tuple[str, str]] = {}
    for key, meta, content in list_memory_files(get_room_dir(room), limit=None):
        episode = system_meta(meta).get(EPISODE_META)
        if not isinstance(episode, str) or episode in rows:
            continue
        title = meta.get("title") if isinstance(meta.get("title"), str) else None
        if not title:
            first = next((ln.strip() for ln in (content or "").splitlines() if ln.strip()), key)
            title = first.lstrip("# ").strip()
        rows[episode] = (key, title)
    return rows


# ── the fields ───────────────────────────────────────────────────────────────


def _is(doc: Doc) -> list[str]:
    out = []
    if doc.message.edited_at is not None:
        out.append("edited")
    if (doc.message.event_metadata or {}).get("conductor"):
        out.append("conductor")
    return out


def _has(doc: Doc) -> list[str]:
    text = doc.message.content or ""
    out = []
    if doc.mentions:
        out.append("mention")
    if _LINK.search(text):
        out.append("link")
    if _MEMORY_LINK.search(text):
        out.append("memory")
    if "```" in text or "`" in text:
        out.append("code")
    if doc.side.scored:
        out.append("scores")
    return out


def _step(doc: Doc) -> list[str]:
    line = (doc.message.event_metadata or {}).get("conductor")
    step = line.get("step") if isinstance(line, dict) else None
    return [step] if isinstance(step, str) else []


def _kind(doc: Doc) -> list[str]:
    return [k for k in (doc.message.event_kind, doc.side.subkind) if k]


def _handle_matches(typed: str, value: str) -> bool:
    return typed.lstrip("@").lower() == value.lower()


def _thread_matches(typed: str, value: str) -> bool:
    typed = typed.lower()
    value = value.lower()
    return (
        typed == value or value.endswith(f":{typed}") or value.rsplit(":", 1)[-1].startswith(typed)
    )


def _day_matches(typed: str, value: str) -> bool:
    stamp = facet_query.parse_time(typed)
    return value == (stamp.date().isoformat() if stamp else typed)


def fields(titles: dict[str, str]) -> list[Field[Doc]]:
    """The message fields, given each task key's title (for ``task:`` and labels)."""

    def task_matches(typed: str, key: str) -> bool:
        typed = typed.lower()
        lowered = key.lower()
        title = titles.get(key, "").lower()
        return typed in (lowered, lowered.rsplit("/", 1)[-1]) or (len(typed) > 2 and typed in title)

    return [
        Field("from", lambda d: [d.message.sender_handle], _handle_matches),
        Field(
            "to",
            lambda d: sorted(
                {
                    *d.side.recipients,
                    *([d.message.recipient_handle] if d.message.recipient_handle else []),
                }
                - {d.message.sender_handle}
            ),
            _handle_matches,
        ),
        Field("mentions", lambda d: list(d.mentions), _handle_matches),
        Field(
            "task",
            lambda d: [d.task] if d.task else [],
            task_matches,
            label=lambda k: titles.get(k, k),
        ),
        Field("in", lambda d: ["thread" if d.thread else "channel"]),
        Field("type", lambda d: [d.message.message_type]),
        Field("kind", _kind),
        Field("status", lambda d: [d.message.event_status] if d.message.event_status else []),
        Field("stance", lambda d: [d.side.stance] if d.side.stance else []),
        Field("step", _step),
        Field("is", _is),
        Field("has", _has),
        Field(
            "day", lambda d: [d.message.created_at.astimezone(UTC).date().isoformat()], _day_matches
        ),
        Field("thread", lambda d: [d.thread] if d.thread else [], _thread_matches, facet=False),
    ]


# ── the search ───────────────────────────────────────────────────────────────


def parse(raw: str, *, now: datetime | None = None) -> FacetQuery:
    """Parse ``raw``; a value outside a closed field's set is a reported problem.

    The clause stays (it matches nothing, which is the truth), so the count
    and the problem agree.
    """
    query = facet_query.parse(raw, FIELDS, aliases=ALIASES, at_field="from", now=now)
    unknown = tuple(
        f"{'-' if c.negate else ''}{c.field}:{c.value}"
        for c in query.clauses
        if c.field in CLOSED_VALUES and c.value.lower() not in CLOSED_VALUES[c.field]
    )
    return replace(query, problems=query.problems + unknown) if unknown else query


def _cursor_key(msg: StoredMessage) -> str:
    return f"{msg.created_at.isoformat()}|{msg.id}"


def _apply_cursor(hits: list[tuple[Doc, float]], query: FacetQuery, cursor: str | None) -> int:
    """The index of the first hit after ``cursor`` in the query's order."""
    if not cursor:
        return 0
    if query.sort == "relevance":
        return int(cursor) if cursor.isdigit() else 0
    for i, (doc, _score) in enumerate(hits):
        if _cursor_key(doc.message) == cursor:
            return i + 1
    # The cursor's message is gone (expired, amended away): resume by time.
    stamp_text = cursor.split("|", 1)[0]
    try:
        stamp = datetime.fromisoformat(stamp_text)
    except ValueError:
        return 0
    for i, (doc, _score) in enumerate(hits):
        at = doc.message.created_at
        if (query.sort == "oldest" and at > stamp) or (query.sort != "oldest" and at < stamp):
            return i
    return len(hits)


def search(
    room: str,
    messages: list[StoredMessage],
    raw: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
    context: int = 0,
    now: datetime | None = None,
) -> Result:
    """Search ``messages`` (a room's conversational view) with the query ``raw``."""
    now = now or datetime.now(UTC)
    query = parse(raw, now=now)
    sides = transcript_sides(room)
    rows = thread_rows(room)
    titles = {key: title for key, title in rows.values()}
    live = l9.live_episode_urn(room)

    named_types = {c.value.lower() for c in query.clauses if c.field == "type" and not c.negate}
    timeline = sorted(
        (m for m in messages if m.event_expires_at is None or m.event_expires_at > now),
        key=lambda m: m.created_at,
    )
    docs: list[Doc] = []
    for m in timeline:
        if m.message_type not in PROSE_MESSAGE_TYPES and m.message_type.lower() not in named_types:
            continue
        thread = m.episode if m.episode and m.episode != live else None
        row = rows.get(thread) if thread else None
        docs.append(
            Doc(
                message=m,
                side=sides.get(m.message_id or "", Side()),
                mentions=tuple(persister.parse_mentions(m.content or "")),
                task=row[0] if row else None,
                thread=thread,
            )
        )

    outcome = facet_query.run(
        docs,
        query,
        fields(titles),
        text=lambda d: d.message.content or "",
        when=lambda d: d.message.created_at,
    )
    start = _apply_cursor(outcome.hits, query, cursor)
    page = outcome.hits[start : start + limit]
    end = start + len(page)
    next_cursor = None
    if end < len(outcome.hits) and page:
        next_cursor = str(end) if query.sort == "relevance" else _cursor_key(page[-1][0].message)

    position = {m.id: i for i, m in enumerate(timeline)}
    hits = []
    for doc, score in page:
        before: list[StoredMessage] = []
        after: list[StoredMessage] = []
        if context > 0:
            before, after = _neighbors(
                timeline, position[doc.message.id], doc.message.episode, context
            )
        hits.append(
            Hit(
                doc=doc,
                score=score,
                snippet=facet_query.snippet(doc.message.content or "", query.needles),
                before=before,
                after=after,
            )
        )
    return Result(
        query=query,
        hits=hits,
        total=len(outcome.hits),
        facets=outcome.facets,
        scanned=outcome.scanned,
        next_cursor=next_cursor,
        task_titles=titles,
    )


def _neighbors(
    timeline: list[StoredMessage], at: int, episode: str | None, n: int
) -> tuple[list[StoredMessage], list[StoredMessage]]:
    """Up to ``n`` prose messages either side of ``at`` in the same channel or thread."""

    def same(m: StoredMessage) -> bool:
        return m.episode == episode and m.message_type in PROSE_MESSAGE_TYPES

    before = [m for m in reversed(timeline[:at]) if same(m)][:n]
    after = [m for m in timeline[at + 1 :] if same(m)][:n]
    return list(reversed(before)), after


def scope_of(query: FacetQuery) -> dict[str, Any]:
    """The interpretation the search ran under, for the response to echo."""
    return {
        "text": query.text,
        "clauses": [
            {"field": c.field, "value": c.value, "negate": c.negate} for c in query.clauses
        ],
        "after": query.after,
        "before": query.before,
        "sort": query.sort,
        "problems": list(query.problems),
    }
