# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Backend-as-room-infrastructure: the persister / durable inbox.

The backend runs as moderator on the room's SLIM group channel and consumes it.
This module is that consumer, and it does four things as each message flows past:

1. **Persister.** Appends each message to the room's transcript
   (``log/transcript.jsonl``, one JSON record per line) so it survives, is
   git-shareable, and is written O(1) per message — a *distinct* artifact from
   the episode-scoped ``log/episodes/*`` records ``l9_episode`` writes.

2. **Durable inbox.** SLIM keeps **no** messages for an offline member: a
   broadcast that happened while a member was gone is never replayed on rejoin.
   So mycelium tracks each agent's delivery position (:class:`DeliveryLog`)
   and, when an agent **reconnects**, **re-serves** the tail it missed — targeted
   point-to-point (not a broadcast), so the rest of the room is untouched.

3. **Trigger-watcher.** Recognizes ``@``-summon tokens in a message and calls a
   summon hook (defaulting to a log when no engine is wired).

4. **plan-compile hook.** On a ``commit:converged`` envelope it fires the
   ``on_converged`` seam the task-sync consumer runs ``task_compiler`` off of;
   the persister itself does **not** compile — it just fires the seam.

5. **Memory-sync receiver.** On a ``knowledge`` envelope — from a real SLIM
   arrival or the sender's own :meth:`RoomPersister.ingest_local` loopback
   alike — it applies the carried write to this backend's local store via
   :func:`app.services.memory_sync.apply_knowledge`, closing the loop the
   emit side (``_broadcast_memory_write`` / :mod:`app.services.task_sync`)
   opens. Unlike the summon/converged hooks this isn't a pluggable engine
   seam: the applier is stateless and version-idempotent, so it always runs.

The pure pieces (:class:`DeliveryLog`, the transcript read/write, the trigger
detection) carry no SLIM dependency and are unit-tested without a node;
:class:`RoomPersister` is the thin async loop that drives them over a live
:class:`~app.services.l9_slim.L9SlimChannel`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.schemas import MessageType
from app.services import l9, memory_sync
from app.services.l9_slim import ChannelReceiveTimeout

# Stable namespace so a transcript record maps to the same synthetic
# ``StoredMessage.id`` on every read (the envelope id is the seed).
_MESSAGE_ID_NS = uuid.UUID("6f1d2c3b-4a59-6e7d-8c9b-0a1b2c3d4e5f")

if TYPE_CHECKING:
    import slim_bindings

    from app.services.in_memory_store import StoredMessage
    from app.services.l9_models import L9
    from app.services.l9_slim import L9SlimChannel

logger = logging.getLogger(__name__)

# The transcript is a plain append-only JSONL file per room
# (``log/transcript.jsonl``): one JSON record per line, written O(1) per message
# and deliberately separate from ``log/episodes/*`` (episode-scoped) so the two
# never clobber each other.
TRANSCRIPT_FILENAME = "log/transcript.jsonl"

# An ``@``-summon token: ``@`` followed by a handle (letter/digit start, then
# word chars or hyphens). Guarded so it doesn't fire mid-word (e.g. an email).
_SUMMON_RE = re.compile(r"(?:^|(?<=[\s(<]))@([A-Za-z0-9][\w-]*)")


# ── Envelope helpers ─────────────────────────────────────────────────────────


def envelope_sender(envelope: L9) -> str | None:
    """The sending handle of an envelope (first actor), or None."""
    actors = envelope.header.participants.actors
    return actors[0].id if actors else None


def envelope_recipients(envelope: L9) -> list[str]:
    """The addressed recipients of an envelope (every actor after the sender)."""
    actors = envelope.header.participants.actors
    return [a.id for a in actors[1:]] if len(actors) > 1 else []


def envelope_message_id(envelope: L9) -> str | None:
    message = envelope.header.message
    return message.id if message is not None else None


def is_converged(envelope: L9) -> bool:
    """True for a ``commit:converged`` envelope (the plan-compile trigger)."""
    header = envelope.header
    return header.kind.value == "commit" and header.subkind == "converged"


def _iter_text(value: Any) -> Iterable[str]:
    """Yield every string leaf in a nested content value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_text(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_text(v)


def parse_mentions(text: str) -> list[str]:
    """Handles ``@``-mentioned in one plain-text string.

    The backend's ``@``-parse: map ``@agent-x`` tokens in a human's
    message to L9 recipients. De-duplicated preserving first-seen order. A bare
    ``word@host`` is **not** a mention (the ``@`` must start the string or follow
    whitespace / ``(`` / ``<``), so an email address never wakes an agent.
    """
    seen: dict[str, None] = {}
    for match in _SUMMON_RE.findall(text):
        seen.setdefault(match, None)
    return list(seen)


def find_summons(content: dict[str, Any]) -> list[str]:
    """Handles ``@``-summoned in a message's human-facing content.

    Scans every string in ``content`` except the additive ``l9`` envelope (which
    agents never read), de-duplicated preserving first-seen order.
    """
    seen: dict[str, None] = {}
    for key, value in content.items():
        if key == "l9":
            continue
        for text in _iter_text(value):
            for match in parse_mentions(text):
                seen.setdefault(match, None)
    return list(seen)


# ── Transcript record + delivery cursors (pure) ──────────────────────────────


@dataclass
class TranscriptRecord:
    """One recorded channel message: its id, sender, kind, and full content."""

    message_id: str
    sender: str
    kind: str
    subkind: str | None
    content: dict[str, Any]
    recorded_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender": self.sender,
            "kind": self.kind,
            "subkind": self.subkind,
            "content": self.content,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TranscriptRecord:
        return cls(
            message_id=data["message_id"],
            sender=data.get("sender", ""),
            kind=data.get("kind", ""),
            subkind=data.get("subkind"),
            content=data.get("content", {}),
            recorded_at=data.get("recorded_at", ""),
        )


class DeliveryLog:
    """A room's ordered transcript plus a per-agent delivery position.

    The transcript is the ordered list of recorded messages. Each *known* handle
    carries a cursor: the count of leading records already delivered to it. A
    present member's cursor advances as records are recorded (SLIM delivered them
    live); an offline member's cursor freezes, so the messages recorded while it
    was gone become its **undelivered tail** — exactly what the durable inbox
    re-serves on reconnect.
    """

    def __init__(
        self,
        records: list[TranscriptRecord] | None = None,
        cursors: dict[str, int] | None = None,
    ) -> None:
        self._records: list[TranscriptRecord] = list(records or [])
        # Cursors are loaded alongside records on resume. Clamp each to the valid
        # range [0, len(records)] so a cursor file that drifted from the transcript
        # (e.g. one write landed and the other didn't across a crash) can never
        # index out of bounds — a stale-high cursor just re-serves nothing, a
        # stale-low one re-serves a bounded, in-range tail.
        n = len(self._records)
        self._cursors: dict[str, int] = {
            str(h): max(0, min(int(pos), n)) for h, pos in (cursors or {}).items()
        }

    @property
    def records(self) -> list[TranscriptRecord]:
        return list(self._records)

    @property
    def cursors(self) -> dict[str, int]:
        """A snapshot of each known handle's delivery position, for persistence."""
        return dict(self._cursors)

    def knows(self, handle: str) -> bool:
        """True once ``handle`` has ever been tracked (join or delivery)."""
        return handle in self._cursors

    def track(self, handle: str, *, caught_up: bool = True) -> None:
        """Register ``handle``. ``caught_up`` starts it at the transcript end
        (a first join missed nothing that preceded it); otherwise at the start."""
        if handle in self._cursors:
            return
        self._cursors[handle] = len(self._records) if caught_up else 0

    def record(
        self,
        record: TranscriptRecord,
        *,
        delivered_to: Iterable[str],
        recipients: Iterable[str] = (),
    ) -> None:
        """Append ``record``; advance the cursor of every present member.

        A present member received the broadcast live, so its cursor moves to the
        new end. Absent members (not in ``delivered_to``) are left behind.

        An addressed ``recipient`` that is absent AND not yet tracked (e.g. an
        ``@``-mentioned agent this very message is inviting) has its cursor started
        *at* this message, so its first wake replays the mention that summoned it.
        Without this a first-join tracks at the transcript end and the triggering
        mention is silently skipped.
        """
        start = len(self._records)
        self._records.append(record)
        end = len(self._records)
        delivered = set(delivered_to)
        for handle in delivered:
            self._cursors[handle] = end
        for handle in recipients:
            if handle not in delivered and handle not in self._cursors:
                self._cursors[handle] = start

    def undelivered(self, handle: str) -> list[TranscriptRecord]:
        """Records recorded but not yet delivered to ``handle`` (its missed tail)."""
        pos = self._cursors.get(handle, len(self._records))
        return self._records[pos:]

    def position(self, handle: str) -> int:
        """``handle``'s delivery cursor — the transcript end if never tracked.

        The same cursor the durable inbox re-serves from, so server-held
        ``await`` (a pull) and reconnect re-serve (a push) share one persisted
        delivery position instead of the process-local one ``await`` used to keep.
        """
        return self._cursors.get(handle, len(self._records))

    def advance(self, handle: str, pos: int) -> None:
        """Move ``handle``'s cursor forward to ``pos`` (clamped, never backward).

        Registers the handle if new, so a first ``await`` that consumes to the
        transcript end is remembered across a restart instead of re-initializing
        to "now" each process. Never rewinds: a lower ``pos`` is ignored, so a
        drain can't un-deliver a tail an earlier live send already advanced past.
        """
        end = len(self._records)
        clamped = max(0, min(int(pos), end))
        current = self._cursors.get(handle)
        if current is None or clamped > current:
            self._cursors[handle] = clamped

    def mark_caught_up(self, handle: str) -> None:
        """Advance ``handle`` to the transcript end (after a re-serve)."""
        self._cursors[handle] = len(self._records)


def record_from(
    envelope: L9, content: dict[str, Any], *, now: str | None = None
) -> TranscriptRecord:
    """Build a :class:`TranscriptRecord` from a released envelope + its content."""
    return TranscriptRecord(
        message_id=envelope_message_id(envelope) or "",
        sender=envelope_sender(envelope) or "",
        kind=envelope.header.kind.value,
        subkind=envelope.header.subkind,
        content=content,
        recorded_at=now or datetime.now(UTC).isoformat(),
    )


# ── Transcript persistence (markdown + jsonl block) ──────────────────────────


def _transcript_line(record: TranscriptRecord) -> str:
    """Serialize one record to its canonical JSONL line (no trailing newline)."""
    return json.dumps(record.to_json(), sort_keys=True)


def _parse_jsonl(text: str) -> list[TranscriptRecord]:
    """Parse a plain JSONL transcript body back into records."""
    records: list[TranscriptRecord] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(TranscriptRecord.from_json(json.loads(stripped)))
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("skipping malformed transcript line")
    return records


def load_transcript(room: str) -> list[TranscriptRecord]:
    """Read a room's persisted ``log/transcript.jsonl`` (empty when none exists)."""
    from app.services.filesystem import get_room_dir

    path = get_room_dir(room) / TRANSCRIPT_FILENAME
    if not path.exists():
        return []
    return _parse_jsonl(path.read_text(encoding="utf-8"))


def append_transcript(room: str, record: TranscriptRecord) -> None:
    """Append one record to ``log/transcript.jsonl`` in O(1) (best-effort)."""
    try:
        from app.services.filesystem import get_room_dir

        path = get_room_dir(room) / TRANSCRIPT_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(_transcript_line(record) + "\n")
    except Exception:
        logger.exception("transcript append failed for room %s", room)


def write_transcript(room: str, records: list[TranscriptRecord]) -> None:
    """Rewrite a room's whole transcript to ``log/transcript.jsonl``.

    A full-file rewrite for seeding a transcript wholesale (tests); the hot path
    appends via :func:`append_transcript` instead of re-rendering the full list.
    """
    try:
        from app.services.filesystem import get_room_dir

        path = get_room_dir(room) / TRANSCRIPT_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(_transcript_line(r) + "\n" for r in records)
        path.write_text(body, encoding="utf-8")
    except Exception:
        logger.exception("transcript write failed for room %s", room)


# L9 record kinds promoted into the room chat view on a cold read, mirroring the
# frontend's ``L9_RAISE_UP_TYPES`` (contracts/l9-surface.json): ``knowledge`` (a
# memory push, e.g. a distilled extraction or the synced plan) and ``commit`` (an
# aligner consensus). Chat itself (an ``exchange`` with a ``message``/``reply``
# payload) is projected as a plain broadcast above; these ride as their
# ``l9_<kind>`` frame instead — the exact shape the live SSE bus pushes
# (:func:`l9_bus_frame`), so the frontend decodes a refresh identically to the
# live stream instead of dropping the row (the "temporary" raise-up rows bug).
_RAISE_UP_KINDS = frozenset({"knowledge", "commit"})


def _conversational_text(content: dict[str, Any]) -> str | None:
    """The human-facing chat text of a record, or None if it isn't chat.

    Only a human ``message`` and an agent ``reply`` are chat; presence/ping and
    other control payloads carry no chat text and stay out of the list.
    """
    payload_type = content.get("l9", {}).get("payload", {}).get("type")
    text = content.get("content")
    if payload_type not in ("message", "reply") or not isinstance(text, str) or not text:
        return None
    return text


def parse_recorded_at(recorded_at: str) -> datetime | None:
    """Read a record's ``recorded_at`` back as an aware datetime, or ``None``.

    Naive input is read as UTC. Every other timestamp the message list sorts
    against is aware, and mixing the two raises rather than misordering.
    """
    from app.services.filesystem import parse_timestamp

    return parse_timestamp(recorded_at)


def amended_target(subkind: str | None, parents: Any) -> str | None:
    """The id an ``exchange:amend`` revises, read off its causal parents.

    An amend carries exactly one parent — the message it revises — so the
    supersede link is the existing ``message.parents`` field rather than a new
    one. Anything else (a different subkind, no parent) is not an amendment.
    """
    if subkind != l9.AMEND_SUBKIND or not isinstance(parents, list) or not parents:
        return None
    target = parents[0]
    return target if isinstance(target, str) and target else None


def collapse_amendments(messages: list[StoredMessage]) -> list[StoredMessage]:
    """Fold each message together with the amendments revising it, newest wins.

    The transcript is append-only: an amendment is a recorded event and every
    version of the text stays on disk. This is the read-side derivation over that
    log — the same contract as the link and search indexes — so a reader sees one
    message carrying its latest text, stamped ``edited_at``.

    An amendment of an amendment resolves down the chain to the message that
    started it, so the fold is always one message and its revisions. An amendment
    folds only into a message from the **same sender** that is present in this
    view; one that matches nothing stays a row of its own rather than vanishing.
    An amendment nobody can attribute is still something that was said, and
    swallowing it would be the read path inventing a deletion.
    """
    by_id: dict[str, StoredMessage] = {}
    for m in messages:
        by_id[str(m.id)] = m
        if m.message_id:
            by_id[m.message_id] = m

    def origin(message: StoredMessage) -> StoredMessage | None:
        """Walk an amendment's parents to the original message it revises."""
        seen = {message.id}
        target = by_id.get(message.amends) if message.amends else None
        while target is not None and target.amends and target.id not in seen:
            seen.add(target.id)
            target = by_id.get(target.amends)
        return target if target is not None and not target.amends else None

    folded: list[StoredMessage] = []
    revised: dict[uuid.UUID, StoredMessage] = {}
    for m in messages:
        target = origin(m) if m.amends else None
        if target is None or target.sender_handle != m.sender_handle:
            folded.append(m)
            continue
        current = revised.get(target.id)
        if current is None or current.created_at <= m.created_at:
            revised[target.id] = m

    if not revised:
        return folded
    return [
        replace(m, content=r.content, edited_at=r.created_at) if (r := revised.get(m.id)) else m
        for m in folded
    ]


def stored_message_from_record(
    room: str, record: TranscriptRecord, *, fallback: datetime | None = None
) -> StoredMessage | None:
    """Project a transcript record into the ``StoredMessage`` the list/UI reads.

    Returns None for a non-conversational, non-raise-up record. The synthetic id is
    derived from the envelope id so it's stable across reads, and ``message_id``
    carries that envelope id as the cross-store correlation key (dedup against
    ``in_memory_store``).

    ``fallback`` stands in when a record carries no readable ``recorded_at`` —
    :func:`conversational_messages` passes the neighbouring record's stamp, the
    tightest true bound the append-ordered transcript offers. Without one the row
    keeps ``StoredMessage``'s read-time default, which sorts it to the newest end
    of the feed no matter when it was actually recorded.
    """
    from app.services.in_memory_store import StoredMessage

    text = _conversational_text(record.content)
    if text is not None:
        # Chat: a plain broadcast row carrying the prose.
        message_type: str = MessageType.BROADCAST
        content = text
    elif record.kind in _RAISE_UP_KINDS:
        # A promoted L9 system frame (memory push / consensus): carry the whole
        # envelope as the ``l9_<kind>`` frame the live stream uses, so the cold
        # read reproduces the live view instead of dropping it on refresh.
        message_type = f"l9_{record.kind}"
        content = json.dumps(record.content)
    else:
        return None
    header = record.content.get("l9", {}).get("header", {})
    episode = header.get("message", {}).get("episode")
    seed = record.message_id or f"{record.recorded_at}:{record.sender}"
    msg = StoredMessage(
        room_name=room,
        sender_handle=record.sender or l9.SYSTEM_ACTOR_ID,
        message_type=message_type,
        content=content,
        episode=episode if isinstance(episode, str) else None,
        message_id=record.message_id or None,
        amends=amended_target(record.subkind, header.get("message", {}).get("parents")),
        id=uuid.uuid5(_MESSAGE_ID_NS, seed),
    )
    recorded = parse_recorded_at(record.recorded_at) or fallback
    if recorded is not None:
        msg.created_at = recorded
    return msg


# Per-room cache of the mapped conversational view, invalidated when the
# transcript file changes, so a hot UI poll re-stats (cheap) rather than
# re-parsing the whole file every read.
_conversational_cache: dict[str, tuple[tuple[int, int], list[StoredMessage]]] = {}


def _stat_stamp(path: Path) -> tuple[int, int] | None:
    """A (mtime_ns, size) cache stamp for ``path``, or None if it doesn't exist."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _project_transcript(room: str, records: list[TranscriptRecord]) -> list[StoredMessage]:
    """Project a whole transcript, healing records whose ``recorded_at`` is unusable.

    An unstamped record inherits the nearest stamp around it in append order —
    the record before it, or, for a leading run, the first stamped record after.
    That keeps it where it was written instead of letting a read-time default
    date it to now and float it to the end of the feed.
    """
    stamps = [parse_recorded_at(r.recorded_at) for r in records]
    earlier: datetime | None = None
    for i, stamp in enumerate(stamps):
        if stamp is None:
            stamps[i] = earlier
        else:
            earlier = stamp
    later: datetime | None = None
    for i in reversed(range(len(stamps))):
        if stamps[i] is None:
            stamps[i] = later
        else:
            later = stamps[i]
    projected = [
        stored_message_from_record(room, record, fallback=stamp)
        for record, stamp in zip(records, stamps, strict=True)
    ]
    return [m for m in projected if m is not None]


def conversational_messages(room: str) -> list[StoredMessage]:
    """The room's conversational history, projected from the durable transcript.

    The read path's source of truth for chat: it survives restarts (the transcript
    is on disk) and both post paths converge here (``respond`` and a human
    broadcast both land in the transcript). Event-ledger rows live only in
    ``in_memory_store`` and are merged in by the route.
    """
    from app.services.filesystem import get_room_dir

    path = get_room_dir(room) / TRANSCRIPT_FILENAME
    stamp = _stat_stamp(path)
    if stamp is None:
        _conversational_cache.pop(room, None)
        return []
    cached = _conversational_cache.get(room)
    if cached is not None and cached[0] == stamp:
        return list(cached[1])
    messages = _project_transcript(room, load_transcript(room))
    _conversational_cache[room] = (stamp, messages)
    return list(messages)


def room_conversation(room: str) -> list[StoredMessage]:
    """A room's full conversational view: durable transcript + live in-memory rows.

    The transcript survives restarts and both post paths converge on it; the
    in-memory ``in_memory_store`` rows are the live view and carry the ledger fields
    (ttl/status) plus the ids clients already hold. Where a message is in both,
    the ``in_memory_store`` row wins and the transcript only fills what memory lost.
    Dedup is by envelope ``message_id`` — a distinct id space from
    ``StoredMessage.id``. The merged view is then folded by
    :func:`collapse_amendments`, so a revised message reads as one row carrying
    its latest text while the transcript keeps every version.
    """
    from app.services import in_memory_store

    mem = in_memory_store.list_messages(room)
    live_ids = {m.message_id for m in mem if m.message_id}
    disk = [m for m in conversational_messages(room) if m.message_id not in live_ids]
    return collapse_amendments(disk + mem)


def prose_messages(room: str) -> list[StoredMessage]:
    """The room's chat, oldest first — what was actually *said*, by type.

    :func:`room_conversation` is the whole feed: chat, the promoted ``l9_*``
    frames (whose content is a serialized envelope) and the coordination
    lifecycle rows. A reader that wants the conversation itself selects on
    :data:`~app.schemas.PROSE_MESSAGE_TYPES` — the type the projection already
    assigned — instead of re-deciding per message what a payload looks like.
    """
    from app.schemas import PROSE_MESSAGE_TYPES

    chat = [m for m in room_conversation(room) if m.message_type in PROSE_MESSAGE_TYPES]
    chat.sort(key=lambda m: m.created_at)
    return chat


def l9_bus_frame(room: str, record: TranscriptRecord) -> dict[str, Any]:
    """Project a transcript record into the L9 wire frame the SSE bus carries.

    The single shape the frontend L9 inspector reads (``l9_<kind>`` + the full
    ``content`` envelope). Shared by the live push (:meth:`Persister._publish_to_bus`)
    and the history replay (:func:`l9_wire_history`) so backfilled and live frames
    are byte-identical.
    """
    episode = record.content.get("l9", {}).get("header", {}).get("message", {}).get("episode")
    return {
        "id": record.message_id,
        "sender_handle": record.sender or l9.SYSTEM_ACTOR_ID,
        "message_type": f"l9_{record.kind}",
        "content": json.dumps(record.content),
        "created_at": record.recorded_at,
        "room_name": room,
        "episode": episode if isinstance(episode, str) else None,
    }


def l9_wire_history(room: str, limit: int = 200) -> list[dict[str, Any]]:
    """The room's L9 wire feed replayed from the durable transcript (oldest first).

    The live inspector is fed only by the bus (SSE, no history), so a freshly
    opened tab misses everything before it connected. This projects the transcript
    through the same frame shape so the tab can seed itself, then append live — the
    history-then-live pattern the room chat feed already uses. Returns at most the
    last ``limit`` frames.
    """
    records = load_transcript(room)
    if limit and len(records) > limit:
        records = records[-limit:]
    return [l9_bus_frame(room, r) for r in records]


# Delivery cursors persist next to the transcript so a reconnecting agent's
# missed tail survives a backend restart. A dot-prefixed .json — not a markdown
# memory — so it stays out of the memory/search surface (which globs ``*.md``).
def _cursors_path(room: str) -> Path:
    from app.services.filesystem import get_room_dir

    return get_room_dir(room) / "log" / ".delivery-cursors.json"


def load_cursors(room: str) -> dict[str, int]:
    """Read a room's persisted delivery cursors (empty when none exists)."""
    path = _cursors_path(room)
    try:
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return {str(h): int(pos) for h, pos in data.items()}
    except (OSError, ValueError, TypeError):
        logger.warning("could not load delivery cursors for room %s; starting empty", room)
    return {}


def write_cursors(room: str, cursors: dict[str, int]) -> None:
    """Persist a room's delivery cursors alongside the transcript (best-effort)."""
    try:
        path = _cursors_path(room)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cursors))
    except Exception:
        logger.exception("delivery-cursor write failed for room %s", room)


# ── The receive loop ─────────────────────────────────────────────────────────

SummonHook = Callable[[str, "L9", list[str], str], None]
ConvergedHook = Callable[["L9"], None]
# Called with the handle of a member that dropped off the channel, so the
# moderator can update its membership — presence, not a fatal error.
MemberLeftHook = Callable[[str], None]

# Consecutive genuine transport failures before the loop gives up — keeps a
# torn-down channel from spinning a hot loop while tolerating transient hiccups.
_MAX_CONSECUTIVE_FAILURES = 3

# Substring SLIM puts in the SessionError when a group member drops. This is a
# membership change, not a transport fault: the session is still alive and the
# loop must keep serving the remaining members.
_PARTICIPANT_LEFT_MARKER = "participant disconnected"

# Substrings SLIM puts in a SessionError when the group session is momentarily
# torn down and recreated — the normal churn of rapid invite/remove cycles (a new
# member re-keys the MLS group). These are transient, NOT a transport fault: the
# channel recovers on the next receive, so they must not spend the fatal
# give-up budget the way a real fault does. Bounded separately (below) so a
# session that is *permanently* closed still eventually gives up.
_TRANSIENT_SESSION_MARKERS = (
    "session closed",
    "session is closed",
    "session not found",
    "no active session",
    "session deleted",
    "connection closed",
)
# A generous budget for back-to-back transient churn errors (with a short backoff
# between them) before concluding the session is permanently gone. Normal churn is
# a handful; this absorbs a storm while still bounding a dead session.
_MAX_CONSECUTIVE_TRANSIENT = 40
_CHURN_BACKOFF_S = 0.25


def _classify_receive_error(exc: Exception) -> str:
    """Classify a receive-loop error: ``participant_left`` | ``transient`` | ``fatal``.

    SLIM raises a generic ``SessionError`` for everything, distinguished only by
    message text, so membership churn (a member leaving, a session re-keyed on a
    join) reads the same as a real transport fault until we look at the string.
    """
    text = str(exc).lower()
    if _PARTICIPANT_LEFT_MARKER in text:
        return "participant_left"
    if any(marker in text for marker in _TRANSIENT_SESSION_MARKERS):
        return "transient"
    return "fatal"


def _handle_from_disconnect(message: str) -> str | None:
    """Parse the leaving handle out of a 'participant disconnected: ws/room/handle/inst' error."""
    _, _, tail = message.partition(_PARTICIPANT_LEFT_MARKER)
    name = tail.split(":", 1)[-1].strip() if ":" in tail else tail.strip()
    parts = [p for p in name.split("/") if p]
    # ws/room/handle[/instance] — the handle is the third segment.
    return parts[2] if len(parts) >= 3 else None


def _default_summon_hook(
    handle: str, envelope: L9, co_summons: list[str], message_text: str = ""
) -> None:
    logger.info("summon hook (skeleton): @%s summoned", handle)


def _default_converged_hook(envelope: L9) -> None:
    # Log-only default for a persister with no plan-sync consumer wired (unit
    # tests / a bare backend).
    logger.info(
        "converged hook (unwired): commit:converged on episode %s; no plan-sync consumer",
        envelope.header.message.episode if envelope.header.message else "?",
    )


class RoomPersister:
    """Consumes one room's channel: persists, re-serves, and watches triggers.

    ``members_provider`` returns the handles currently on the channel (the
    moderator's authoritative membership from
    :class:`~app.services.room_channels.RoomChannelManager`), so the persister
    knows who received each broadcast live. The hooks are skeletons wired to real
    behaviour in later steps.
    """

    def __init__(
        self,
        room: str,
        channel: L9SlimChannel,
        *,
        members_provider: Callable[[], Iterable[str]],
        on_summon: SummonHook | None = None,
        on_converged: ConvergedHook | None = None,
        on_member_left: MemberLeftHook | None = None,
        feed_bus: bool = True,
    ) -> None:
        self.room = room
        self._channel = channel
        self._members_provider = members_provider
        self.on_summon = on_summon or _default_summon_hook
        self.on_converged = on_converged or _default_converged_hook
        self.on_member_left = on_member_left
        self._feed_bus = feed_bus
        # Resume from disk so re-serve survives a backend restart: the transcript
        # supplies the records, and the persisted cursors supply each agent's
        # delivery position — so a member that was offline at shutdown is still
        # recognised as a reconnect and re-served exactly its missed tail.
        self.log = DeliveryLog(load_transcript(room), cursors=load_cursors(room))
        # handle -> most recent inbound MessageContext, for targeted re-serve.
        self._contexts: dict[str, slim_bindings.MessageContext] = {}
        # Message ids ingested this process lifetime, so a message the backend
        # publishes itself (the human proxy) is recorded/fed to the bus exactly
        # once even if SLIM loops the broadcast back to the moderator.
        self._ingested_ids: set[str] = set()
        # Strong refs to in-flight knowledge-apply tasks (apply_knowledge does file
        # IO + reindexing, so it can't run inline in the sync ``_ingest`` call);
        # without this the task could be GC'd mid-flight.
        self._knowledge_tasks: set[asyncio.Task[None]] = set()
        # Health counters surfaced via RoomChannelManager.status(). ``receive_errors``
        # is genuine (fatal) transport faults; ``transient_errors`` is recoverable
        # membership-churn receive errors (retried, not lost) — split so the health
        # surface distinguishes "the channel is faulting" from "the channel is
        # churning". ``reserve_failures``/``reserve_skipped`` make the two ways a
        # missed-message re-serve fails to land visible instead of log-only.
        # ``knowledge_applied``/``knowledge_conflicts`` are the memory-sync receiver's
        # equivalent: how many inbound writes converged vs. lost to a stale base.
        self.reserves = 0
        self.receive_errors = 0
        self.transient_errors = 0
        self.reserve_failures = 0
        self.reserve_skipped = 0
        self.knowledge_applied = 0
        self.knowledge_conflicts = 0

    def _persist_cursors(self) -> None:
        """Snapshot the delivery cursors to disk (best-effort, per mutation)."""
        write_cursors(self.room, self.log.cursors)

    def advance_cursor(self, handle: str, pos: int) -> None:
        """Advance ``handle``'s durable delivery cursor to ``pos`` and persist it.

        The consume side of the durable inbox for a server-held ``await`` caller:
        as ``await`` drains the transcript it commits the new position here so it
        survives a backend restart, rather than the process-local cursor that
        silently reset every handle to "now" on restart.
        """
        self.log.advance(handle, pos)
        self._persist_cursors()

    # -- membership signals (driven by RoomChannelManager) --

    def note_join(self, handle: str) -> bool:
        """Record a membership add; return True if it is a **reconnect**.

        A handle the persister has never seen is a fresh join — it missed nothing
        that preceded it, so it is tracked caught-up and this returns False. A
        handle seen before is a reconnect: caller should :meth:`reserve` its
        missed tail.
        """
        if self.log.knows(handle):
            return True
        self.log.track(handle, caught_up=True)
        self._persist_cursors()
        return False

    async def reserve(self, handle: str) -> int:
        """Re-serve ``handle`` the messages it missed while offline, in order.

        Targeted (point-to-point) so the rest of the room is untouched. Requires
        a cached reply context for ``handle`` (from an earlier message it sent);
        without one there is no route to re-serve to, so it is a no-op until the
        connector holds its own identity. Returns the count re-served.
        """
        missed = self.log.undelivered(handle)
        if not missed:
            return 0
        context = self._contexts.get(handle)
        if context is None:
            # First-wake race: on a handle's FIRST join the moderator has never
            # received a message from it, so there's no point-to-point route to
            # re-serve the tail that triggered the invite — the first wake is
            # silently dropped. WARN so it's visible.
            logger.warning(
                "cannot re-serve %d missed message(s) to %s in room %s: no reply context yet "
                "(first-wake race)",
                len(missed),
                handle,
                self.room,
            )
            self.reserve_skipped += 1
            return 0
        served = 0
        for record in missed:
            try:
                await self._channel.send_content_to(context, record.content)
                served += 1
            except Exception:
                logger.exception("re-serve to %s failed at message %s", handle, record.message_id)
                self.reserve_failures += 1
                break
        if served:
            self.reserves += served
            self.log.mark_caught_up(handle)
            self._persist_cursors()
            logger.info(
                "re-served %d missed message(s) to %s in room %s", served, handle, self.room
            )
        return served

    # -- the loop --

    async def run(self) -> None:
        """Pull from the channel forever, recording and dispatching each message."""
        failures = 0  # consecutive genuine transport faults
        churn = 0  # consecutive transient membership-churn errors
        while True:
            try:
                released, arrived, context = await self._channel.receive_with_context()
            except ChannelReceiveTimeout:
                # A benign idle tick — the receive machinery is alive, no message
                # arrived within the window. Not a fault: reset the runs so a quiet
                # room's channel is never torn down.
                failures = churn = 0
                continue
            except Exception as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                kind = _classify_receive_error(exc)
                if kind == "participant_left":
                    # A member dropping off is a membership change, not a fault: the
                    # session is alive and still serving everyone else. Update
                    # presence and keep going without spending any budget — a member
                    # leaving must never zombie the room.
                    left = _handle_from_disconnect(str(exc))
                    logger.info("participant left room %s: %s", self.room, left or "?")
                    if left and self.on_member_left is not None:
                        with contextlib.suppress(Exception):
                            self.on_member_left(left)
                    failures = churn = 0
                    continue
                if kind == "transient":
                    # The group session was momentarily torn down and recreated —
                    # normal rapid invite/remove churn. It recovers on the next
                    # receive, so back off briefly and keep going rather than
                    # spending the fatal budget. Bounded so a permanently-closed
                    # session still eventually gives up instead of looping forever.
                    failures = 0
                    churn += 1
                    self.transient_errors += 1
                    if churn >= _MAX_CONSECUTIVE_TRANSIENT:
                        logger.error(
                            "persister for room %s STOPPING after %d consecutive transient "
                            "session errors — the channel appears permanently closed",
                            self.room,
                            churn,
                        )
                        return
                    logger.info(
                        "transient session churn on room %s (%d/%d): %s",
                        self.room,
                        churn,
                        _MAX_CONSECUTIVE_TRANSIENT,
                        exc,
                    )
                    await asyncio.sleep(_CHURN_BACKOFF_S)
                    continue
                # A genuine transport fault: spend the give-up budget quickly.
                churn = 0
                failures += 1
                self.receive_errors += 1
                logger.warning(
                    "persister receive error on room %s (%d/%d): %s",
                    self.room,
                    failures,
                    _MAX_CONSECUTIVE_FAILURES,
                    exc,
                )
                if failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "persister for room %s STOPPING after %d repeated errors — channel is now "
                        "a zombie (no re-serve/record) until re-provisioned",
                        self.room,
                        failures,
                    )
                    return
                continue
            failures = churn = 0
            # Cache the arrived sender's reply context for future re-serve.
            sender = envelope_sender(arrived)
            if sender is not None:
                first_context = sender not in self._contexts
                self._contexts[sender] = context
                # First-wake race: the @-mention that triggered a member's
                # invite is recorded undelivered for it, but reserve() at invite
                # time was a no-op — the member hadn't spoken yet, so there was no
                # point-to-point route. Its first message (the join hello) gives us
                # that route; re-serve the missed tail now so the first wake isn't
                # silently dropped. reserve() marks caught-up, so this can't
                # double-deliver against the invite-time/reconnect re-serve.
                if first_context and self.log.undelivered(sender):
                    await self.reserve(sender)
            for envelope, content in released:
                self._ingest(envelope, content)

    def ingest_local(
        self, envelope: L9, content: dict[str, Any], *, list_write: bool = False
    ) -> None:
        """Ingest a message the moderator published itself (locally originated).

        The backend records the message into the transcript directly, so the
        transcript and UI bus see it regardless of whether SLIM delivers a
        broadcast back to its own sender. :meth:`_ingest` de-dupes by message id,
        so a loopback of the same broadcast is a no-op.

        ``list_write`` controls whether the message is also written to the
        in-memory list store: the human-proxy broadcast path pre-writes nothing to
        ``in_memory_store`` (the transcript is its record, read back by
        :func:`conversational_messages`), while ``respond`` (``/reply``) passes
        ``list_write=True`` so an agent's turn is visible live, before it's flushed
        to the durable transcript — otherwise ``respond`` and ``room send`` would
        land in different stores.

        Also marks the message delivered in the channel's causal buffer: a locally
        ingested message never passes through ``receive_with_context``, so without
        this an agent reply parented on it (``build_reply`` threads
        ``parents=[woke_id]``) is held in the buffer forever and never recorded.
        """
        self._channel.note_delivered(envelope)
        self._ingest(envelope, content, list_write=list_write)

    def _ingest(self, envelope: L9, content: dict[str, Any], *, list_write: bool = True) -> None:
        # Keepalive pings exist only to reset a member's SLIM liveness (which the
        # datapath already did before this message reached us), so they carry no
        # transcript value. Drop them here — otherwise a member's ~20s keepalive
        # would append to the durable transcript forever (log spam + cursor churn).
        if content.get("l9", {}).get("payload", {}).get("type") == "keepalive":
            return
        mid = envelope_message_id(envelope)
        if mid is not None:
            if mid in self._ingested_ids:
                return
            self._ingested_ids.add(mid)
        record = record_from(envelope, content)
        present = set(self._members_provider())
        self.log.record(record, delivered_to=present, recipients=envelope_recipients(envelope))
        append_transcript(self.room, record)
        self._persist_cursors()
        # The list store is the live/fast view; the durable transcript is the read
        # path's source of truth. SLIM arrivals (agent replies) and ``respond`` write
        # here so they're visible immediately; the human-proxy broadcast skips it
        # (``list_write=False``) since the transcript already carries it.
        if list_write:
            self._record_to_list_store(record)
        if self._feed_bus:
            self._publish_to_bus(record)
        # Triggers: @-summon and commit:converged (skeleton hooks). The full
        # summon list is passed to every hook call so an engine summoned alongside
        # other handles (``@aligner @a @b``) can scope the run to those co-mentions.
        summons = find_summons(content)
        message_text = content.get("content", "") if isinstance(content, dict) else ""
        for handle in summons:
            try:
                self.on_summon(handle, envelope, summons, message_text)
            except Exception:
                logger.exception("summon hook failed for @%s", handle)
        if is_converged(envelope):
            try:
                self.on_converged(envelope)
            except Exception:
                logger.exception("converged hook failed")
        if memory_sync.is_knowledge(envelope):
            self._schedule_knowledge_apply(envelope)

    def _schedule_knowledge_apply(self, envelope: L9) -> None:
        """Apply an inbound ``knowledge`` write off the ingest path.

        Fires for a real SLIM arrival and for the sender's own
        :meth:`ingest_local` loopback alike — ``apply_knowledge`` is
        version-idempotent (see :mod:`app.services.memory_sync`), so re-applying
        a write this store already holds is a silent no-op, not a double-write.
        Scheduled as a tracked background task since ``_ingest`` is sync but the
        applier does file IO + reindexing; never re-broadcasts, so this cannot
        loop with the emit side (``_broadcast_memory_write`` / ``task_sync``).
        """
        write = memory_sync.knowledge_write_from_envelope(envelope)
        if write is None:
            logger.warning("malformed knowledge envelope on room %s; not applied", self.room)
            return
        task = asyncio.create_task(self._apply_knowledge(write))
        self._knowledge_tasks.add(task)
        task.add_done_callback(self._knowledge_tasks.discard)

    async def _apply_knowledge(self, write: memory_sync.KnowledgeWrite) -> None:
        try:
            result = await memory_sync.apply_knowledge(self.room, write)
        except Exception:
            logger.exception("apply_knowledge failed for %s/%s", self.room, write.key)
            return
        if result.conflict:
            self.knowledge_conflicts += 1
        elif result.applied:
            self.knowledge_applied += 1

    def _publish_to_bus(self, record: TranscriptRecord) -> None:
        """Feed the recorded message to the in-process bus so the SSE UI sees it.

        The bus (``routes/stream.py``) is the frontend's live feed; agent messages
        arrive over SLIM, not HTTP, so the persister is what keeps that feed fed.
        Best-effort — never fail a record over a UI push.
        """
        try:
            from app.bus import bus, room_channel

            bus.publish(room_channel(self.room), l9_bus_frame(self.room, record))
        except Exception:
            logger.debug("bus publish from persister failed for room %s", self.room, exc_info=True)

    def _record_to_list_store(self, record: TranscriptRecord) -> None:
        """Mirror a conversational record into the in-memory list store (the live view).

        The durable transcript is the read path's source of truth; this write keeps
        the message visible immediately (before a cold read re-projects the
        transcript). Conversational payloads only — presence/control payloads stay
        in the transcript/bus, out of the chat list. Carries the envelope id so a
        cold read dedups this row against its transcript projection.
        """
        msg = stored_message_from_record(self.room, record)
        if msg is None:
            return
        try:
            from app.services import in_memory_store

            in_memory_store.add_message(self.room, msg)
        except Exception:
            logger.debug("list-store write failed for room %s", self.room, exc_info=True)
