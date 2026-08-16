# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Cross-entity search: one query over memories, episodes, messages, rooms, agents.

This is the content counterpart to the UI's command palette — the palette runs
*actions*, this finds *things* — and it is one endpoint rather than a client-side
merge of five. Ranking heterogeneous results is the whole difficulty, and it can
only be done where every candidate is in hand: a client fanning out to per-type
endpoints would have to invent a common scale after the fact, and each caller
would invent a different one.

Scoring
-------
Every candidate gets a **lexical** score on one 0…1 scale: each query term is
worth 3 if it *is* the item's label, 2 if it appears in the label, 1 if it
appears only in the body, normalized by the best possible total. So an exact
name beats a partial name beats a body mention, whatever the type.

Memories additionally get a **semantic** score from the room's embedding index
(the same one ``memory search`` uses), rescaled from the floor below which a
cosine hit is noise and capped short of 1 — a memory that merely *reads like*
the query never outranks something the query literally names. The two are
combined by ``max``: semantic recall adds matches, it doesn't inflate them.

A small per-type prior then breaks ties, in the spirit of the palette's recency
bonus: cheap, precise navigation targets (a room, an agent) edge out a message
that scored the same, and nothing large enough to override a decisive match.

With no free text at all — ``#atlas episode:`` — there is nothing to score, so
the scope alone stands and results come back newest-first. Typeahead should
answer a half-typed query with the room's recent episodes, not an empty list.

Cost
----
This runs per keystroke, so each room's index and transcript are read through a
stat-stamped cache (mirroring ``persister.conversational_messages``): a repeated
query re-stats the files rather than re-parsing them. The embedding pass is the
one genuinely expensive step, so it runs only when memories are in scope and the
free text is long enough to mean something.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from app.services import persister, search_index
from app.services.filesystem import list_room_names, read_room_meta, room_exists
from app.services.search_query import ParsedQuery

logger = logging.getLogger(__name__)

#: Most hits of any one type kept before the global sort, so a room with a
#: thousand messages can't crowd every other type out of a short result list.
PER_TYPE_CAP = 8

#: Newest messages scanned per room. Older chat is reachable through the room's
#: own history; a typeahead that reads every transcript in full is not typeahead.
MESSAGE_SCAN = 400

#: Below this many characters the embedding pass is skipped — a one- or
#: two-letter query has no semantic content worth the cosine sweep.
SEMANTIC_MIN_CHARS = 3

#: Cosine similarity below which a memory hit is noise rather than a match.
SEMANTIC_FLOOR = 0.35

#: What a purely semantic match can score at best. Strictly under the 1.0 an
#: exact label match earns, so "reads like the query" never beats "is the query".
SEMANTIC_CEILING = 0.70

#: The score every candidate takes when the query is pure scope and there is
#: nothing to rank by. Results then order by recency.
BROWSE_SCORE = 0.2

#: Tie-break weight by type. Small on purpose — it reorders near-equal matches
#: and leaves a decisive one alone.
TYPE_PRIOR: dict[str, float] = {
    "room": 0.06,
    "agent": 0.05,
    "episode": 0.03,
    "memory": 0.02,
    "message": 0.0,
}

_SNIPPET_CHARS = 160


@dataclass(frozen=True)
class Hit:
    """One result, in the shape every type is flattened into."""

    type: str
    room: str
    #: Type-specific identifier the UI navigates by: a memory key, an episode
    #: short id, a message uuid, a room name, an agent handle.
    id: str
    title: str
    subtitle: str
    snippet: str
    kind: str | None
    #: ISO timestamp, or "" where the entity carries none.
    timestamp: str
    score: float


# ── scoring ───────────────────────────────────────────────────────────────────


def lexical_score(terms: list[str], label: str, body: str) -> float:
    """How well ``label``/``body`` answer ``terms``, on a 0…1 scale.

    Every term must land somewhere for a full score, so a two-word query is not
    satisfied by a document that only contains one of the words.
    """
    if not terms:
        return 0.0
    label = label.lower()
    body = body.lower()
    total = 0.0
    for term in terms:
        if label == term:
            total += 3.0
        elif term in label:
            total += 2.0
        elif term in body:
            total += 1.0
    return total / (3.0 * len(terms))


def semantic_score(similarity: float) -> float:
    """Rescale a cosine similarity into the lexical scale, capped below an exact hit."""
    if similarity <= SEMANTIC_FLOOR:
        return 0.0
    scaled = (similarity - SEMANTIC_FLOOR) / (1.0 - SEMANTIC_FLOOR)
    return min(1.0, scaled) * SEMANTIC_CEILING


def _ranked(score: float, result_type: str) -> float:
    return min(1.0, score + TYPE_PRIOR.get(result_type, 0.0))


def _snippet(text: str, terms: list[str]) -> str:
    """A one-line window of ``text``, centred on the first term that appears in it."""
    flat = " ".join(text.split())
    if len(flat) <= _SNIPPET_CHARS:
        return flat
    lowered = flat.lower()
    at = next((i for i in (lowered.find(t) for t in terms) if i >= 0), -1)
    if at < 0:
        return flat[:_SNIPPET_CHARS].rstrip() + "…"
    start = max(0, at - _SNIPPET_CHARS // 3)
    window = flat[start : start + _SNIPPET_CHARS].strip()
    return ("…" if start > 0 else "") + window + "…"


# ── cached room readers ───────────────────────────────────────────────────────

# Keyed by the index file's absolute path, holding the (mtime_ns, size) the
# projection came from. Confined to the read path — writers go through
# search_index and never see this — so a write is picked up on the next call by
# its new stamp.
_memory_cache: dict[str, tuple[tuple[int, int], list[dict]]] = {}


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _memory_records(room: str) -> list[dict]:
    """A room's search-index records, cached against the index file's stamp."""
    path = search_index.index_path(room)
    stamp = _stamp(path)
    if stamp is None:
        _memory_cache.pop(str(path), None)
        return []
    cached = _memory_cache.get(str(path))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    records = search_index.load_index(room)
    _memory_cache[str(path)] = (stamp, records)
    return records


# ── per-type candidate collection ─────────────────────────────────────────────


def _rooms_in_scope(query: ParsedQuery) -> list[str]:
    """The rooms to search. A named room that doesn't exist searches nothing."""
    if query.rooms:
        return [r for r in query.rooms if room_exists(r)]
    return list_room_names()


def _matches_actor(query: ParsedQuery, *handles: str | None) -> bool:
    """True when no actor scope is set, or any of ``handles`` is one of them."""
    if not query.actors:
        return True
    present = {h.lstrip("@").lower() for h in handles if h}
    return bool(present & set(query.actors))


def _matches_kind(query: ParsedQuery, *kinds: str | None) -> bool:
    """True when no kind scope is set, or any of ``kinds`` is one of them.

    Fails closed: with a kind scope set, a candidate that carries no kind at all
    is out. ``kind:converged`` asks for converged things, and a room is not one.
    """
    if not query.kinds:
        return True
    present = {k.lower() for k in kinds if k}
    return bool(present & set(query.kinds))


def _room_hits(query: ParsedQuery, rooms: list[str]) -> list[Hit]:
    if not _matches_kind(query, None):
        return []
    terms = query.terms
    hits: list[Hit] = []
    for name in rooms:
        meta = read_room_meta(name) or {}
        description = str(meta.get("description") or "")
        score = BROWSE_SCORE if not terms else lexical_score(terms, name, description)
        if score <= 0:
            continue
        hits.append(
            Hit(
                type="room",
                room=name,
                id=name,
                title=name,
                subtitle=str(meta.get("mas_id") or ""),
                snippet=description,
                kind=None,
                timestamp=str(meta.get("created_at") or ""),
                score=score,
            )
        )
    return hits


def _agent_hits(query: ParsedQuery, rooms: list[str]) -> list[Hit]:
    from app.services.agent_registry import room_agents

    terms = query.terms
    hits: list[Hit] = []
    for room in rooms:
        for agent in room_agents(room):
            if not _matches_kind(query, agent.kind, agent.adapter):
                continue
            # An actor scope names the agent itself here, not its author.
            if query.actors and agent.handle.lower() not in query.actors:
                continue
            body = " ".join(filter(None, [agent.description, agent.team, agent.owner]))
            score = BROWSE_SCORE if not terms else lexical_score(terms, agent.handle, body)
            if score <= 0:
                continue
            detail = agent.kind or agent.adapter
            hits.append(
                Hit(
                    type="agent",
                    room=room,
                    id=agent.handle,
                    title=agent.handle,
                    subtitle=f"{room} · {detail}",
                    snippet=agent.description,
                    kind=agent.kind or agent.adapter,
                    timestamp="",
                    score=score,
                )
            )
    return hits


def _episode_hits(query: ParsedQuery, rooms: list[str]) -> list[Hit]:
    from app.services.episode_records import room_episodes

    terms = query.terms
    hits: list[Hit] = []
    for room in rooms:
        for ep in room_episodes(room, limit=100):
            state = ep["subkind"] or ep["outcome"]
            if not _matches_kind(query, state, ep["outcome"]):
                continue
            if not _matches_actor(query, *ep["participants"]):
                continue
            body = " ".join([ep["topic"], state, *ep["participants"]])
            score = BROWSE_SCORE if not terms else lexical_score(terms, ep["short_id"], body)
            if score <= 0:
                continue
            hits.append(
                Hit(
                    type="episode",
                    room=room,
                    id=ep["short_id"],
                    title=f"episode {ep['short_id']}",
                    subtitle=f"{room} · {state} · {ep['message_count']} msg",
                    snippet=", ".join(ep["participants"]) or ep["topic"],
                    kind=state,
                    timestamp=str(ep["updated_at"] or ""),
                    score=score,
                )
            )
    return hits


def _memory_text(record: dict) -> str:
    return str(record.get("content_text") or "")


def _memory_hits(query: ParsedQuery, rooms: list[str]) -> list[tuple[Hit, dict]]:
    """Lexical memory candidates, paired with the index record they came from.

    The record rides along so the semantic pass can raise a candidate's score
    without loading the index a second time.
    """
    terms = query.terms
    hits: list[tuple[Hit, dict]] = []
    for room in rooms:
        for record in _memory_records(room):
            key = str(record.get("key") or "")
            if not key:
                continue
            author = record.get("updated_by") or record.get("created_by")
            if not _matches_actor(query, str(author) if author else None):
                continue
            # A memory's kind is its namespace, so `kind:decisions` reads as the
            # `decisions/` folder rather than as an L9 subkind.
            namespace = key.rsplit("/", 1)[0] if "/" in key else ""
            if not _matches_kind(query, namespace or None):
                continue
            text = _memory_text(record)
            score = BROWSE_SCORE if not terms else lexical_score(terms, key, text)
            hit = Hit(
                type="memory",
                room=room,
                id=key,
                title=key,
                subtitle=f"{room}{' · ' + namespace if namespace else ''}",
                snippet=_snippet(text, terms),
                kind=namespace or None,
                timestamp=str(record.get("updated_at") or ""),
                score=score,
            )
            hits.append((hit, record))
    return hits


async def _apply_semantics(
    query: ParsedQuery, candidates: list[tuple[Hit, dict]]
) -> list[tuple[Hit, dict]]:
    """Raise each memory candidate's score by its embedding similarity to the query."""
    from app.services.embedding import embed_text

    embedding = await asyncio.to_thread(embed_text, query.text)
    raised: list[tuple[Hit, dict]] = []
    for hit, record in candidates:
        stored = record.get("embedding")
        if not stored:
            raised.append((hit, record))
            continue
        similarity = search_index.cosine_similarity(embedding, stored)
        score = max(hit.score, semantic_score(similarity))
        raised.append((replace(hit, score=score), record))
    return raised


def _message_hits(query: ParsedQuery, rooms: list[str]) -> list[Hit]:
    terms = query.terms
    hits: list[Hit] = []
    for room in rooms:
        messages = persister.room_conversation(room)
        messages.sort(key=lambda m: m.created_at, reverse=True)
        for msg in messages[:MESSAGE_SCAN]:
            if not _matches_actor(query, msg.sender_handle, msg.recipient_handle):
                continue
            if not _matches_kind(query, msg.message_type, msg.event_kind):
                continue
            text = msg.content or ""
            # The sender is part of the label: "@avery postgres" should find what
            # avery said about postgres, not only messages naming avery.
            score = BROWSE_SCORE if not terms else lexical_score(terms, msg.sender_handle, text)
            if score <= 0:
                continue
            hits.append(
                Hit(
                    type="message",
                    room=room,
                    id=str(msg.id),
                    title=_snippet(text, terms) or msg.message_type,
                    subtitle=f"{room} · @{msg.sender_handle}",
                    snippet=text[:_SNIPPET_CHARS],
                    kind=msg.message_type,
                    timestamp=msg.created_at.isoformat(),
                    score=score,
                )
            )
    return hits


# ── the search itself ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    #: Matches per type before the global trim, so a caller can say "12 memories"
    #: even when only three fit the list.
    counts: dict[str, int]


async def search(query: ParsedQuery, *, limit: int = 20) -> SearchResult:
    """Run ``query`` across every entity type in scope and rank the results."""
    if query.is_empty:
        return SearchResult(hits=[], counts={})

    rooms = _rooms_in_scope(query)
    by_type: dict[str, list[Hit]] = {}

    if query.wants("room"):
        by_type["room"] = _room_hits(query, rooms)
    if query.wants("agent"):
        by_type["agent"] = _agent_hits(query, rooms)
    if query.wants("episode"):
        by_type["episode"] = _episode_hits(query, rooms)
    if query.wants("message"):
        by_type["message"] = _message_hits(query, rooms)
    if query.wants("memory"):
        candidates = _memory_hits(query, rooms)
        if len(query.text) >= SEMANTIC_MIN_CHARS:
            candidates = await _apply_semantics(query, candidates)
        by_type["memory"] = [hit for hit, _ in candidates if hit.score > 0]

    # A pure-scope query has nothing to score by, so recency is the order; with
    # terms, score leads and recency breaks the remaining ties.
    newest_first = not query.terms
    order = (
        (lambda h: (h.timestamp, TYPE_PRIOR.get(h.type, 0.0)))
        if newest_first
        else (lambda h: (h.score, h.timestamp))
    )

    # Order within a type first, so the per-type cap keeps that type's best.
    counts: dict[str, int] = {}
    kept: list[Hit] = []
    for result_type, hits in by_type.items():
        counts[result_type] = len(hits)
        hits.sort(key=order, reverse=True)
        kept.extend(hits[:PER_TYPE_CAP])

    if not newest_first:
        kept = [replace(h, score=_ranked(h.score, h.type)) for h in kept]
    kept.sort(key=order, reverse=True)

    return SearchResult(hits=kept[:limit], counts=counts)
