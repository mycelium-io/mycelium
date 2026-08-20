# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Threads — a conversation scope *inside* a room, derived from the L9 causal DAG.

A room is one SLIM group channel and every message is a broadcast on it, so past
two participants the transcript tangles: which reply answers which prompt is
guesswork. A **thread** is the unit smaller than "the whole room" — something to
follow, filter, address, and ``await`` on.

Threads are **not** a SLIM primitive and deliberately not a second channel. They
follow the episode pattern (a scope *over* the room's existing channel) and are
**derived, never stored**: a message already carries ``message.parents``, so the
thread it belongs to falls out of the causal DAG the wire has always had. There is
no parallel ``thread_id`` field to keep in sync, and a transcript written before
threads existed threads correctly on first read.

The rules, in order, for one transcript record:

1. A record on a **scoped episode** (any episode URN that isn't the room's catch-all
   ``…:live``) belongs to that episode's thread. *An episode is a typed thread* — a
   negotiation is the one conversation scope mycelium already had, so threads
   generalize it rather than sitting beside it as a second grouping.
2. A record that declares itself a thread root (``payload.data.thread_root``, what
   ``mycelium thread new`` posts) opens a thread rooted at itself — the one case
   causality can't express, since a freshly-opened thread has neither a parent to
   hang off nor a child to root it yet.
3. Otherwise the record threads on its **first parent**: it inherits that parent's
   thread, or — when the parent has none — opens a thread *rooted at the parent*.
   A thread is therefore born the moment someone replies to a message, and its id
   is the root message's id.
4. Otherwise the record is room-level: no thread.

Addressing a thread never needs a new field either. ``respond --thread T`` parents
the reply on ``T``, and rule 3 does the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.persister import TranscriptRecord

# Payload types that carry no conversation: liveness plumbing, never a thread.
_NON_CONVERSATIONAL = frozenset({"presence", "keepalive"})

# The catch-all episode a room's un-negotiated traffic rides
# (``l9.episode_urn(room, "live")``). It scopes nothing, so it opens no thread.
LIVE_EPISODE_SUFFIX = ":live"

# How much of a root message's first line becomes the thread's display title.
_TITLE_LIMIT = 80

# The L9 payload-data flag a deliberately-opened thread's root message carries.
THREAD_ROOT_KEY = "thread_root"


def _header(content: dict[str, Any]) -> dict[str, Any]:
    l9 = content.get("l9")
    header = l9.get("header") if isinstance(l9, dict) else None
    return header if isinstance(header, dict) else {}


def _message(content: dict[str, Any]) -> dict[str, Any]:
    message = _header(content).get("message")
    return message if isinstance(message, dict) else {}


def _payload_type(content: dict[str, Any]) -> str | None:
    l9 = content.get("l9")
    payload = l9.get("payload") if isinstance(l9, dict) else None
    return payload.get("type") if isinstance(payload, dict) else None


def episode_of(content: dict[str, Any]) -> str | None:
    """The episode URN a record's envelope carries, if any."""
    episode = _message(content).get("episode")
    return episode if isinstance(episode, str) and episode else None


def is_scoped_episode(episode: str | None) -> bool:
    """True for a real negotiation episode — not the room's catch-all ``…:live``."""
    return bool(episode) and not str(episode).endswith(LIVE_EPISODE_SUFFIX)


def episode_thread_id(episode: str) -> str:
    """The thread id of an episode: its session id (the URN's last segment).

    Deliberately the same short id the episode inspector shows, so
    ``mycelium thread show <id>`` and ``mycelium room episodes`` name one scope.
    """
    return episode.rsplit(":", 1)[-1]


def opens_thread(content: dict[str, Any]) -> bool:
    """True when a message declares itself the root of a new thread.

    The one case the causal DAG can't express on its own: a thread opened
    *before* anything replies into it (``mycelium thread new``) has no parent to
    hang off and no child yet to root it. So the opener says so in its own L9
    payload data — additive, inside the envelope, and needed only for a
    deliberately-opened thread. Every other thread is pure causality.
    """
    l9 = content.get("l9")
    payload = l9.get("payload") if isinstance(l9, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None
    return bool(isinstance(data, dict) and data.get(THREAD_ROOT_KEY))


def _parents(content: dict[str, Any]) -> list[str]:
    parents = _message(content).get("parents")
    return [p for p in parents if isinstance(p, str) and p] if isinstance(parents, list) else []


class ThreadIndex:
    """Incremental message-id → thread-id assignment over a room's transcript.

    Fed records in transcript order; :meth:`extend` processes only the tail it
    hasn't seen, so a long-poll can keep an index warm across iterations instead
    of re-deriving the whole room on every tick.
    """

    def __init__(self) -> None:
        self._by_message: dict[str, str] = {}
        self._consumed = 0

    @property
    def consumed(self) -> int:
        """How many records this index has already assigned."""
        return self._consumed

    def extend(self, records: list[TranscriptRecord]) -> None:
        """Assign every record past the ones already consumed."""
        for record in records[self._consumed :]:
            self.add(record)

    def add(self, record: TranscriptRecord) -> str | None:
        """Assign one record (in transcript order); return its thread id."""
        self._consumed += 1
        content = record.content if isinstance(record.content, dict) else {}
        if _payload_type(content) in _NON_CONVERSATIONAL:
            return None
        mid = record.message_id or ""
        thread = self._derive(content, mid)
        if thread and mid:
            self._by_message[mid] = thread
        return thread

    def _derive(self, content: dict[str, Any], message_id: str) -> str | None:
        episode = episode_of(content)
        if is_scoped_episode(episode):
            return episode_thread_id(str(episode))
        if opens_thread(content) and message_id:
            return message_id
        for parent in _parents(content):
            inherited = self._by_message.get(parent)
            if inherited:
                return inherited
            # The parent carries no thread of its own, so this reply opens one and
            # the parent is its root — including when the parent isn't in this
            # transcript at all (``--thread T`` names a thread by its root id).
            self._by_message[parent] = parent
            return parent
        return None

    def thread_of(self, message_id: str | None) -> str | None:
        """The thread of a message id, or None when it is room-level."""
        return self._by_message.get(message_id) if message_id else None

    def thread_of_record(self, record: TranscriptRecord) -> str | None:
        """The thread of an already-indexed record."""
        return self.thread_of(record.message_id)

    def as_map(self) -> dict[str, str]:
        """A snapshot of message id → thread id."""
        return dict(self._by_message)


def thread_map(records: list[TranscriptRecord]) -> dict[str, str]:
    """Message id → thread id for a whole transcript."""
    index = ThreadIndex()
    index.extend(records)
    return index.as_map()


@dataclass
class ThreadSummary:
    """One thread's shape for the list/detail surfaces."""

    id: str
    kind: str  # "chat" | "episode"
    title: str
    root_message_id: str | None = None
    last_message_id: str | None = None
    episode: str | None = None
    participants: list[str] = field(default_factory=list)
    message_count: int = 0
    started_at: str = ""
    last_message_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "root_message_id": self.root_message_id,
            "last_message_id": self.last_message_id,
            "episode": self.episode,
            "participants": list(self.participants),
            "message_count": self.message_count,
            "started_at": self.started_at,
            "last_message_at": self.last_message_at,
        }


def _title_from(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first[:_TITLE_LIMIT] + ("…" if len(first) > _TITLE_LIMIT else "")


def summarize(records: list[TranscriptRecord]) -> list[ThreadSummary]:
    """Every thread in a transcript, most recently active first.

    Two passes: the assignment is only complete once the whole transcript is
    indexed, because a thread's root is assigned *retroactively* — a room-level
    message becomes a root the moment something replies to it. The second pass
    then folds each record into its thread, root included (that's what makes
    ``thread show`` read as a conversation and not as its tail).
    """
    assigned = thread_map(records)
    summaries: dict[str, ThreadSummary] = {}
    for record in records:
        thread = assigned.get(record.message_id or "")
        if not thread:
            continue
        summary = summaries.get(thread)
        if summary is None:
            episode = episode_of(record.content)
            summary = ThreadSummary(
                id=thread,
                kind="episode" if is_scoped_episode(episode) else "chat",
                title="",
                root_message_id=record.message_id or None,
                episode=str(episode) if is_scoped_episode(episode) else None,
                started_at=record.recorded_at,
            )
            summaries[thread] = summary
        text = record.content.get("content") if isinstance(record.content, dict) else None
        if not summary.title and isinstance(text, str) and text.strip():
            summary.title = _title_from(text)
        if record.sender and record.sender not in summary.participants:
            summary.participants.append(record.sender)
        summary.message_count += 1
        summary.last_message_id = record.message_id or summary.last_message_id
        summary.last_message_at = record.recorded_at
    ordered = sorted(summaries.values(), key=lambda s: s.last_message_at, reverse=True)
    for summary in ordered:
        if not summary.title:
            summary.title = f"({summary.kind} thread {summary.id[:8]})"
    return ordered


# ── Room-level surface (reads the durable transcript) ────────────────────────


def room_thread_map(room: str) -> dict[str, str]:
    """Message id → thread id for a room, derived from its durable transcript."""
    from app.services.persister import load_transcript

    return thread_map(load_transcript(room))


def room_threads(room: str, *, limit: int = 50) -> list[ThreadSummary]:
    """A room's threads, most recently active first."""
    from app.services.persister import load_transcript

    threads = summarize(load_transcript(room))
    return threads[:limit] if limit else threads


class AmbiguousThread(LookupError):
    """A thread reference matched more than one thread."""

    def __init__(self, ref: str, matches: list[str]) -> None:
        super().__init__(f"thread {ref!r} is ambiguous: {', '.join(matches)}")
        self.ref = ref
        self.matches = matches


def resolve(room: str, ref: str) -> ThreadSummary | None:
    """Resolve a thread reference: an exact id, an id prefix, or an episode URN.

    Prefix resolution is what makes threads usable from a shell — a chat thread's
    id is its root message's UUID, and nobody types those. Raises
    :class:`AmbiguousThread` when a prefix matches several.
    """
    if not ref:
        return None
    needle = ref.strip()
    if is_scoped_episode(needle):
        needle = episode_thread_id(needle)
    threads = room_threads(room, limit=0)
    exact = [t for t in threads if t.id == needle]
    if exact:
        return exact[0]
    matches = [t for t in threads if t.id.startswith(needle)]
    if len(matches) > 1:
        raise AmbiguousThread(ref, [t.id for t in matches])
    return matches[0] if matches else None
