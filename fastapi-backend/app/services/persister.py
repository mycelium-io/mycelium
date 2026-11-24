# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
A room's log on the hub: every message recorded, and who has read how far.

Each message the room records passes through :meth:`RoomPersister.record`,
which does three things:

1. **Persists.** Appends the message to the room's transcript
   (``log/transcript.jsonl``, one JSON record per line), written O(1) per
   message, a *distinct* artifact from the episode-scoped ``log/episodes/*``
   records ``episode_state`` writes.

2. **Keeps read positions.** Each agent's position in the transcript
   (:class:`DeliveryLog`, and per thread :class:`EpisodeCursors`) survives a
   restart, so ``await`` hands an agent exactly what it hasn't read.

3. **Watches triggers.** Who the message asks (``@``-mentions, turns,
   interrupts) goes to the summon and asked hooks, and the record to the app's
   live stream and the recorded hook.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.schemas import MessageType
from app.services import message_format

# Stable namespace so a transcript record maps to the same synthetic
# ``StoredMessage.id`` on every read (the envelope id is the seed).
_MESSAGE_ID_NS = uuid.UUID("6f1d2c3b-4a59-6e7d-8c9b-0a1b2c3d4e5f")

if TYPE_CHECKING:
    from app.services.in_memory_store import StoredMessage
    from app.services.message_models import MyceliumMessage

logger = logging.getLogger(__name__)

# The transcript is a plain append-only JSONL file per room
# (``log/transcript.jsonl``): one JSON record per line, written O(1) per message
# and deliberately separate from ``log/episodes/*`` (episode-scoped) so the two
# never clobber each other.
TRANSCRIPT_FILENAME = "log/transcript.jsonl"

# An ``@``-summon token: ``@`` followed by a handle (letter/digit start, then
# word chars, hyphens or dots, never ending on a dot, so ``@avery.quinn`` is
# one handle and a sentence's full stop stays out). Guarded so it doesn't fire
# mid-word (e.g. an email).
# ``@~handle`` is a silent mention (``contracts/mentions.json``): the ``~`` keeps
# it out of this pattern, so it never wakes, addresses or summons anyone.
# ``@!handle`` is an interrupting mention: a mention like ``@handle`` that also
# stops the agent mid-turn, so it is in this pattern and in its own.
# A handle may end in ``:name``, a subagent's (``app.services.subagents``),
# spelled the same way.
_PART = r"[A-Za-z0-9](?:[\w.-]*[\w-])?"
_HANDLE = rf"({_PART}(?::{_PART})?)"
_SUMMON_RE = re.compile(r"(?:^|(?<=[\s(<]))@!?" + _HANDLE)
_SILENT_RE = re.compile(r"(?:^|(?<=[\s(<]))@~" + _HANDLE)
_INTERRUPT_RE = re.compile(r"(?:^|(?<=[\s(<]))@!" + _HANDLE)
_NAMED_RE = re.compile(r"(?:^|(?<=[\s(<]))@[~!]?" + _HANDLE)

# Code is quoted, never addressed: a handle inside a code span or a fenced block
# is no mention of any kind (``contracts/mentions.json``). A fence opens on a
# line of three or more backticks or tildes (any indent) and runs to a line of
# the same character at least as long, or to the end of the text, as Markdown
# draws it. A backtick fence's info string holds no backtick.
_FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")
#: What code is replaced with before matching: no word character, no
#: whitespace, so it neither extends a handle nor starts one.
_CODE_MASK = "\x00"


def _mask(text: str) -> str:
    return "".join("\n" if c == "\n" else _CODE_MASK for c in text)


def _blank_fences(text: str) -> str:
    out: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        if fence is not None:
            if re.fullmatch(rf"[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", line):
                fence = None
            out.append(_mask(line))
            continue
        opened = _FENCE_OPEN.match(line)
        if opened and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            fence = opened.group(1)
            out.append(_mask(line))
            continue
        out.append(line)
    return "\n".join(out)


def _backtick_run(text: str, start: int) -> int:
    end = start
    while end < len(text) and text[end] == "`":
        end += 1
    return end


def blank_code(text: str) -> str:
    """``text`` with its fenced blocks and code spans masked, same length.

    A code span opens on a run of backticks and closes on the next run of the
    same length within its paragraph; a run with no such close is literal
    backticks, not code. Newlines are kept, so the start-of-line rule for a
    mention still holds outside code.
    """
    text = _blank_fences(text)
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] != "`":
            out.append(text[i])
            i += 1
            continue
        run_end = _backtick_run(text, i)
        run = run_end - i
        close = -1
        k = run_end
        while k < len(text):
            if text[k] != "`":
                k += 1
                continue
            k_end = _backtick_run(text, k)
            if k_end - k == run:
                close = k
                break
            k = k_end
        if close == -1 or _BLANK_LINE.search(text, run_end, close):
            out.append(text[i:run_end])
            i = run_end
            continue
        out.append(_mask(text[i : close + run]))
        i = close + run
    return "".join(out)


# ── Envelope helpers ─────────────────────────────────────────────────────────


def envelope_sender(envelope: MyceliumMessage) -> str | None:
    """The sending handle of an envelope (first actor), or None."""
    actors = envelope.header.participants.actors
    return actors[0].id if actors else None


def envelope_recipients(envelope: MyceliumMessage) -> list[str]:
    """The addressed recipients of an envelope (every actor after the sender)."""
    actors = envelope.header.participants.actors
    return [a.id for a in actors[1:]] if len(actors) > 1 else []


def envelope_message_id(envelope: MyceliumMessage) -> str | None:
    message = envelope.header.message
    return message.id if message is not None else None


#: ``@here`` and ``@all`` name a group, never a member called that
#: (``app.services.groups``), so no handle parse returns them.
_GROUP_NAMES = frozenset({"here", "all"})


def _handles(pattern: re.Pattern[str], text: str) -> list[str]:
    """The handles ``pattern`` finds outside code, first-seen order, groups left out."""
    seen: dict[str, None] = {}
    for match in pattern.findall(blank_code(text)):
        if match.lower() not in _GROUP_NAMES:
            seen.setdefault(match, None)
    return list(seen)


def parse_mentions(text: str) -> list[str]:
    """Handles ``@``-mentioned in one plain-text string.

    The backend's ``@``-parse: map ``@agent-x`` tokens in a human's
    message to message recipients. De-duplicated preserving first-seen order. A bare
    ``word@host`` is **not** a mention (the ``@`` must start the string or follow
    whitespace / ``(`` / ``<``), so an email address never wakes an agent, and
    a handle inside code (:func:`blank_code`) is quoted, not mentioned.
    """
    return _handles(_SUMMON_RE, text)


def parse_silent_mentions(text: str) -> list[str]:
    """Handles named with a silent ``@~handle`` in one plain-text string.

    A silent mention refers to a member without asking anything of it: it is
    searchable as ``mentions:`` and drawn as a member, but it is no message recipient,
    rings no doorbell and summons no engine. Same boundary rule and order as
    :func:`parse_mentions`.
    """
    return _handles(_SILENT_RE, text)


def parse_named(text: str) -> list[str]:
    """Every handle named in one plain-text string, in the order named, however
    it was written: ``@handle``, ``@~handle`` or ``@!handle``. For reading who a
    command names (a conductor binding its roles), not who it asks: only the
    loud forms ask (:func:`parse_mentions`)."""
    return _handles(_NAMED_RE, text)


def parse_interrupt_mentions(text: str) -> list[str]:
    """Handles named with an interrupting ``@!handle`` in one plain-text string.

    Each is a mention too (:func:`parse_mentions` lists it), and asks for more:
    stop the agent mid-turn so it reads the message now rather than when its
    turn ends. Same boundary rule and order as :func:`parse_mentions`.
    """
    return _handles(_INTERRUPT_RE, text)


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
    carries a cursor: the count of leading records already delivered to it,
    advanced as its ``await`` reads them. The messages recorded past it are its
    **undelivered tail**, which its next ``await`` hands it.
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
        delivered_to: Iterable[str] = (),
        recipients: Iterable[str] = (),
    ) -> None:
        """Append ``record``; move the cursor of each handle in ``delivered_to``
        to the new end.

        An addressed ``recipient`` that is not yet tracked (an ``@``-mentioned
        agent reading the room for the first time) has its cursor started *at*
        this message, so its first ``await`` hands it the mention that asked
        for it rather than starting past it.
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
        """``handle``'s delivery cursor: the transcript end if never tracked."""
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

    def rename(self, old: str, new: str) -> None:
        """Carry ``old``'s position to ``new`` (the further one wins), so a
        renamed agent doesn't read the room again from where ``new`` stood."""
        cursors = rename_positions(self._cursors, old, new)
        self._cursors.clear()
        self._cursors.update(cursors)


class EpisodeCursors:
    """Per-``(handle, episode)`` delivery positions over the same transcript.

    A room has one ordered transcript; a thread is a *tag* on records inside it,
    not a second log. So a thread cursor is an index into that same list — the
    count of leading records this handle has already been served **for that
    thread** — and reading a thread costs no second store.

    Deliberately *not* the room-wide cursor of :class:`DeliveryLog`. Scoping an
    ``await`` to a thread must not consume the handle's room inbox: an agent that
    watches one task still has every mention made to it in the room waiting when
    it looks. The two positions move independently, and both persist.

    A handle with no position on a thread starts at its **room-wide** one, so the
    fork happens where it is standing: the ``@``-mention that pulled it into the
    thread anchored that cursor (:meth:`DeliveryLog.record`) and is therefore
    still ahead of it, while everything it had already consumed stays consumed.
    """

    def __init__(self, cursors: dict[str, dict[str, int]] | None = None) -> None:
        self._by_episode: dict[str, dict[str, int]] = {
            str(episode): {str(h): int(pos) for h, pos in positions.items()}
            for episode, positions in (cursors or {}).items()
        }

    @property
    def snapshot(self) -> dict[str, dict[str, int]]:
        """A copy for persistence, keyed episode -> handle -> position."""
        return {episode: dict(positions) for episode, positions in self._by_episode.items()}

    def position(self, handle: str, episode: str, *, default: int) -> int:
        """``handle``'s position on ``episode``, clamped to ``default`` on a first read."""
        return self._by_episode.get(episode, {}).get(handle, default)

    def advance(self, handle: str, episode: str, pos: int, *, limit: int) -> None:
        """Move the position forward to ``pos`` (clamped to ``limit``, never backward)."""
        clamped = max(0, min(int(pos), limit))
        positions = self._by_episode.setdefault(episode, {})
        if clamped > positions.get(handle, -1):
            positions[handle] = clamped

    def rename(self, old: str, new: str) -> None:
        """Carry ``old``'s position on every thread to ``new``."""
        self._by_episode = {
            episode: rename_positions(positions, old, new)
            for episode, positions in self._by_episode.items()
        }


def rename_positions(positions: dict[str, int], old: str, new: str) -> dict[str, int]:
    """``positions`` with ``old``'s entry under ``new``; the further of the two wins."""
    if old not in positions:
        return dict(positions)
    out = {h: pos for h, pos in positions.items() if h != old}
    out[new] = max(positions[old], out.get(new, 0))
    return out


def record_episode(record: TranscriptRecord) -> str | None:
    """The episode URN a transcript record rode under, if it carries one."""
    episode = (
        (message_format.envelope_of(record.content).get("header") or {}).get("message") or {}
    ).get("episode")
    return message_format.canonical_urn(episode) if isinstance(episode, str) and episode else None


def read_id(record: TranscriptRecord) -> uuid.UUID:
    """The id the room's history read gives ``record`` (``MessageRead.id``)."""
    return read_id_of(record.message_id or f"{record.recorded_at}:{record.sender}")


def read_id_of(wire_id: str) -> uuid.UUID:
    """The history read's id for the message the wire knows as ``wire_id``."""
    return uuid.uuid5(_MESSAGE_ID_NS, wire_id)


def record_from(
    envelope: MyceliumMessage, content: dict[str, Any], *, now: str | None = None
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


@dataclass
class _Parsed:
    """A room's transcript as far as it has been read: the records, how many
    bytes they came from, and the last bytes of those, to tell the file that
    was read from one written over it."""

    inode: int
    offset: int
    tail: bytes
    records: list[TranscriptRecord]


#: The parsed transcripts of the rooms read most recently, by file, oldest
#: first. A transcript only grows (``append_transcript``), so a read after an
#: append parses the new lines alone; a busy room's transcript is tens of
#: megabytes, and every read parsing all of it held the event loop for a fifth
#: of a second each time.
_parsed: dict[str, _Parsed] = {}
_parsed_lock = threading.Lock()
#: How many rooms keep their parsed transcript. Parsed, a transcript takes about
#: four times its size on disk, so keeping every room ever read would hold a
#: few hundred megabytes on a hub with a handful of busy rooms. A room that
#: falls out is read in full the next time it's read.
_PARSED_ROOMS = 2
#: How many of the last bytes read are kept to check the file is the same one.
_TAIL_BYTES = 256


def load_transcript(room: str) -> list[TranscriptRecord]:
    """Read a room's persisted ``log/transcript.jsonl`` (empty when none exists).

    Read once in full, then only what was appended since: the file is
    append-only, so what was parsed stays parsed, for the few rooms read most
    recently (``_PARSED_ROOMS``). A file that's been replaced
    or rewritten (its inode, length or the bytes last read differ) is read in
    full again. The records are shared between callers, which only read them;
    the list is each caller's own.
    """
    from app.services.filesystem import get_room_dir

    path = get_room_dir(room) / TRANSCRIPT_FILENAME
    key = str(path)
    try:
        stat = path.stat()
    except OSError:
        with _parsed_lock:
            _parsed.pop(key, None)
        return []
    with _parsed_lock:
        known = _parsed.pop(key, None)
        with path.open("rb") as fh:
            if known is not None and not _same_file(fh, stat, known):
                known = None
            start = known.offset if known is not None else 0
            fh.seek(start)
            added = fh.read()
        # A line still being written has no newline yet: leave it for next time.
        whole = added[: added.rfind(b"\n") + 1]
        records = (known.records if known is not None else []) + _parse_jsonl(
            whole.decode("utf-8", errors="replace")
        )
        offset = start + len(whole)
        if whole:
            tail = whole[-_TAIL_BYTES:]
            if len(tail) < _TAIL_BYTES and known is not None:
                tail = (known.tail + tail)[-_TAIL_BYTES:]
        else:
            tail = known.tail if known is not None else b""
        _parsed[key] = _Parsed(inode=stat.st_ino, offset=offset, tail=tail, records=records)
        while len(_parsed) > _PARSED_ROOMS:
            del _parsed[next(iter(_parsed))]
        return list(records)


def _same_file(fh: Any, stat: os.stat_result, known: _Parsed) -> bool:
    """Whether the open file is the one ``known`` was read from, grown or not."""
    if stat.st_ino != known.inode or stat.st_size < known.offset:
        return False
    if not known.tail:
        return known.offset == 0
    fh.seek(known.offset - len(known.tail))
    return fh.read(len(known.tail)) == known.tail


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


# message record kinds promoted into the room chat view on a cold read, mirroring the
# frontend's ``RAISE_UP_TYPES`` (contracts/channel-surface.json): ``knowledge`` (a
# memory push, e.g. a distilled extraction) and ``commit`` (a negotiation's
# outcome). Chat itself (an ``exchange`` with a ``message``/``reply``
# payload) is projected as a plain broadcast above; these ride as their
# ``envelope_<kind>`` frame instead — the exact shape the live SSE bus pushes
# (:func:`bus_frame`), so the frontend decodes a refresh identically to the
# live stream instead of dropping the row (the "temporary" raise-up rows bug).
_RAISE_UP_KINDS = frozenset({"knowledge", "commit"})


def _conversational_text(content: dict[str, Any]) -> str | None:
    """The human-facing chat text of a record, or None if it isn't chat.

    Only a human ``message`` and an agent ``reply`` are chat; presence/ping and
    other control payloads carry no chat text and stay out of the list. A
    reaction isn't chat either: it is read as the emoji on another message
    (:func:`reaction_text`).
    """
    envelope = message_format.envelope_of(content)
    if (envelope.get("header") or {}).get("subkind") == message_format.REACTION_SUBKIND:
        return None
    payload_type = (envelope.get("payload") or {}).get("type")
    text = content.get("content")
    if payload_type not in ("message", "reply") or not isinstance(text, str) or not text:
        return None
    return text


def reaction_text(content: dict[str, Any]) -> str | None:
    """A reaction record's text (``@~author 👍``), or None if it isn't one."""
    envelope = message_format.envelope_of(content)
    if (envelope.get("header") or {}).get("subkind") != message_format.REACTION_SUBKIND:
        return None
    text = content.get("content")
    return text if isinstance(text, str) and text else None


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
    if subkind != message_format.AMEND_SUBKIND or not isinstance(parents, list) or not parents:
        return None
    target = parents[0]
    return target if isinstance(target, str) and target else None


def reaction_of(
    subkind: str | None, parents: Any, content: dict[str, Any]
) -> tuple[str, str, bool] | None:
    """The message an ``exchange:reaction`` is on, its emoji, and whether it puts
    the emoji on (``True``) or takes it off. ``None`` for anything else."""
    if subkind != message_format.REACTION_SUBKIND or not isinstance(parents, list) or not parents:
        return None
    target, reaction = parents[0], content.get("reaction")
    if not isinstance(target, str) or not target or not isinstance(reaction, dict):
        return None
    emoji = reaction.get("emoji")
    if not isinstance(emoji, str) or not emoji:
        return None
    return target, emoji, reaction.get("on") is not False


def collapse_reactions(messages: list[StoredMessage]) -> list[StoredMessage]:
    """Fold each reaction into the message it is on, and drop it as a row.

    A reaction is a record like any other, so putting an emoji on and taking it
    off are both kept. The newest record for each (message, person, emoji) wins.
    Unlike an amendment, a reaction whose message isn't in this view is dropped:
    an emoji on its own says nothing.
    """
    if not any(m.reacts for m in messages):
        return messages
    by_id: dict[str, StoredMessage] = {}
    for m in messages:
        by_id[str(m.id)] = m
        if m.message_id:
            by_id[m.message_id] = m

    # (target row id, emoji, who) -> on; a dict keeps the order each was first put on.
    state: dict[tuple[uuid.UUID, str, str], bool] = {}
    for r in sorted((m for m in messages if m.reacts), key=lambda m: m.created_at):
        target = by_id.get(r.reacts or "")
        if target is None or target.reacts or not r.reaction:
            continue
        key = (target.id, r.reaction, r.sender_handle)
        if r.reaction_on and key not in state:
            state[key] = True
        elif key in state:
            state[key] = r.reaction_on

    on: dict[uuid.UUID, dict[str, list[str]]] = {}
    for (target_id, emoji, who), is_on in state.items():
        if is_on:
            on.setdefault(target_id, {}).setdefault(emoji, []).append(who)
    return [
        replace(m, reactions=[{"emoji": e, "by": by} for e, by in on[m.id].items()])
        if m.id in on
        else m
        for m in messages
        if not m.reacts
    ]


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
    :func:`conversational_messages` passes the neighboring record's stamp, the
    tightest true bound the append-ordered transcript offers. Without one the row
    keeps ``StoredMessage``'s read-time default, which sorts it to the newest end
    of the feed no matter when it was actually recorded.
    """
    from app.services.in_memory_store import StoredMessage

    # A reaction projects as a row only so the read path can fold it into its
    # message (:func:`collapse_reactions`); it is never shown as one.
    text = _conversational_text(record.content) or reaction_text(record.content)
    if text is not None:
        # Chat: a plain broadcast row carrying the prose.
        message_type: str = MessageType.BROADCAST
        content = text
    elif record.kind in _RAISE_UP_KINDS:
        # A promoted system frame (memory push / consensus): carry the whole
        # envelope as the ``envelope_<kind>`` frame the live stream uses, so the
        # cold read reproduces the live view instead of dropping it on refresh.
        message_type = message_format.frame_type(record.kind)
        content = json.dumps(record.content)
    else:
        return None
    envelope = message_format.envelope_of(record.content)
    header = envelope.get("header") or {}
    episode = header.get("message", {}).get("episode")
    # A conductor post carries a structured line beside its prose (see
    # ``conductor.LINE_KEY``). The chat projection keeps only prose, so the line
    # rides the message's metadata, and a reload draws the run as the live
    # stream did rather than as the prompts behind it. An ask and its answer
    # (``approvals``) ride the same way, so the app draws the card.
    data = (envelope.get("payload") or {}).get("data") or {}
    lifted = (
        {k: data[k] for k in ("conductor", "ask", "answer") if isinstance(data.get(k), dict)}
        if isinstance(data, dict)
        else {}
    )
    msg = StoredMessage(
        room_name=room,
        sender_handle=record.sender or message_format.SYSTEM_ACTOR_ID,
        message_type=message_type,
        content=content,
        event_metadata=lifted or None,
        episode=episode if isinstance(episode, str) else None,
        message_id=record.message_id or None,
        amends=amended_target(record.subkind, header.get("message", {}).get("parents")),
        id=read_id(record),
    )
    reaction = reaction_of(record.subkind, header.get("message", {}).get("parents"), record.content)
    if reaction is not None:
        msg.reacts, msg.reaction, msg.reaction_on = reaction
    recorded = parse_recorded_at(record.recorded_at) or fallback
    if recorded is not None:
        msg.created_at = recorded
    return msg


@dataclass
class _Projected:
    """A room's conversational view as far as its transcript was projected:
    the last record projected (the same object while the transcript only
    grows, ``load_transcript``), how many records that was, and the last
    usable stamp among them."""

    last: TranscriptRecord
    count: int
    stamp: datetime | None
    messages: list[StoredMessage]


def _stat_stamp(path: Path) -> tuple[int, int] | None:
    """A (mtime_ns, size) cache stamp for ``path``, or None if it doesn't exist."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


# Per-room cache of the mapped conversational view. The UI reads it for every
# thread a board shows, and a busy room appends between most of those reads,
# so what was appended is projected onto it rather than the whole transcript
# again; a rewritten transcript is projected in full.
_conversational_cache: dict[str, _Projected] = {}


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
    records = load_transcript(room)
    if not records:
        _conversational_cache.pop(room, None)
        return []
    cached = _conversational_cache.get(room)
    if (
        cached is not None
        and cached.stamp is not None
        and 0 < cached.count <= len(records)
        and records[cached.count - 1] is cached.last
    ):
        # The same transcript, grown: project what was appended, each
        # unstamped record taking the stamp before it, as a whole read would.
        messages = list(cached.messages)
        earlier = cached.stamp
        for record in records[cached.count :]:
            stamp = parse_recorded_at(record.recorded_at)
            earlier = stamp or earlier
            if (msg := stored_message_from_record(room, record, fallback=earlier)) is not None:
                messages.append(msg)
    else:
        messages = _project_transcript(room, records)
        earlier = next(
            (s for r in reversed(records) if (s := parse_recorded_at(r.recorded_at))), None
        )
    _conversational_cache[room] = _Projected(
        last=records[-1], count=len(records), stamp=earlier, messages=messages
    )
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
    its latest text while the transcript keeps every version, and by
    :func:`collapse_reactions`, so each message carries the emoji on it.
    """
    from app.services import in_memory_store

    mem = in_memory_store.list_messages(room)
    live_ids = {m.message_id for m in mem if m.message_id}
    disk = [m for m in conversational_messages(room) if m.message_id not in live_ids]
    return collapse_reactions(collapse_amendments(disk + mem))


def prose_messages(room: str) -> list[StoredMessage]:
    """The room's chat, oldest first — what was actually *said*, by type.

    :func:`room_conversation` is the whole feed: chat, the promoted ``envelope_*``
    frames (whose content is a serialized envelope) and the coordination
    lifecycle rows. A reader that wants the conversation itself selects on
    :data:`~app.schemas.PROSE_MESSAGE_TYPES` — the type the projection already
    assigned — instead of re-deciding per message what a payload looks like.
    """
    from app.schemas import PROSE_MESSAGE_TYPES

    chat = [m for m in room_conversation(room) if m.message_type in PROSE_MESSAGE_TYPES]
    chat.sort(key=lambda m: m.created_at)
    return chat


def bus_frame(room: str, record: TranscriptRecord) -> dict[str, Any]:
    """Project a transcript record into the wire frame the SSE bus carries.

    The single shape the frontend's channel and Stream read (``envelope_<kind>`` + the
    full ``content`` envelope). Shared by the live push (:meth:`Persister._publish_to_bus`)
    and the history replay (:func:`wire_history`) so backfilled and live frames
    are byte-identical.
    """
    header = message_format.envelope_of(record.content).get("header") or {}
    episode = (header.get("message") or {}).get("episode")
    return {
        "id": record.message_id,
        # The id the room's history read gives the same message, so a client
        # holding both copies can tell they're one.
        "read_id": str(read_id(record)),
        "sender_handle": record.sender or message_format.SYSTEM_ACTOR_ID,
        "message_type": message_format.frame_type(record.kind),
        "content": json.dumps(record.content),
        "created_at": record.recorded_at,
        "room_name": room,
        "episode": episode if isinstance(episode, str) else None,
    }


def wire_history(
    room: str, limit: int = 200, before: datetime | None = None
) -> list[dict[str, Any]]:
    """The room's wire feed replayed from the durable transcript (oldest first).

    The channel and Stream are fed live only by the bus (SSE, no history), so a freshly
    opened tab misses everything before it connected. This projects the transcript
    through the same frame shape so the tab can seed itself, then append live — the
    history-then-live pattern the room chat feed already uses. Returns at most the
    last ``limit`` frames.

    ``before`` narrows that window to what was recorded strictly earlier, which is
    what walking back through the room asks for. A record whose stamp cannot be
    read is kept: dropping it would put a hole in the replay to save a comparison.
    """
    records = load_transcript(room)
    if before is not None:
        records = [
            r
            for r in records
            if (recorded := parse_recorded_at(r.recorded_at)) is None or recorded < before
        ]
    if limit and len(records) > limit:
        records = records[-limit:]
    return [bus_frame(room, r) for r in records]


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


# Thread cursors persist in their own file rather than namespaced into the
# room-wide one: ``load_cursors`` feeds ``DeliveryLog``, which reads every key it
# is handed as a handle, and a composite key there would show up as a phantom
# member in ``knows``/``undelivered``.
def _episode_cursors_path(room: str) -> Path:
    from app.services.filesystem import get_room_dir

    return get_room_dir(room) / "log" / ".thread-cursors.json"


def load_episode_cursors(room: str) -> dict[str, dict[str, int]]:
    """Read a room's persisted per-thread delivery positions (empty when none)."""
    path = _episode_cursors_path(room)
    try:
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return {
                    str(episode): {str(h): int(pos) for h, pos in positions.items()}
                    for episode, positions in data.items()
                    if isinstance(positions, dict)
                }
    except (OSError, ValueError, TypeError):
        logger.warning("could not load thread cursors for room %s; starting empty", room)
    return {}


def write_episode_cursors(room: str, cursors: dict[str, dict[str, int]]) -> None:
    """Persist a room's per-thread delivery positions (best-effort)."""
    try:
        path = _episode_cursors_path(room)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cursors))
    except Exception:
        logger.exception("thread-cursor write failed for room %s", room)


def rename_cursors_on_disk(room: str, old: str, new: str) -> None:
    """:meth:`RoomPersister.rename_handle` for a room with no live persister."""
    write_cursors(room, rename_positions(load_cursors(room), old, new))
    write_episode_cursors(
        room,
        {ep: rename_positions(p, old, new) for ep, p in load_episode_cursors(room).items()},
    )


# ── The receive loop ─────────────────────────────────────────────────────────

SummonHook = Callable[[str, "MyceliumMessage", list[str], str], None]
# Called once per handle a message asks for something, with why (``mention``,
# ``turn`` or ``interrupt``; :mod:`app.services.asks` is the rule): what rings
# the herdr doorbell, and how a persona or a worker hears a turn put to it.
AskedHook = Callable[[str, str, "MyceliumMessage", str], None]
#: Fired once per recorded message with the record as stored (the verifier reads
#: agents' prose off it). Runs after the record is durable and on the bus.
RecordedHook = Callable[["TranscriptRecord"], None]


def _default_summon_hook(
    handle: str, envelope: MyceliumMessage, co_summons: list[str], message_text: str = ""
) -> None:
    logger.info("@%s summoned, with no engine to answer", handle)


class RoomPersister:
    """One room's log: records each message, keeps read positions, and calls
    the trigger hooks."""

    def __init__(
        self,
        room: str,
        *,
        on_summon: SummonHook | None = None,
        on_asked: AskedHook | None = None,
        on_recorded: RecordedHook | None = None,
        feed_bus: bool = True,
    ) -> None:
        self.room = room
        self.on_summon = on_summon or _default_summon_hook
        self.on_asked = on_asked
        self.on_recorded = on_recorded
        self._feed_bus = feed_bus
        # Resumed from disk: the transcript supplies the records, and the
        # persisted cursors each agent's read position, so a restart hands no
        # one the room again from the start.
        self.log = DeliveryLog(load_transcript(room), cursors=load_cursors(room))
        # The same resume, for a thread-scoped ``await``: a per-(handle, thread)
        # position over the transcript above.
        self.episode_cursors = EpisodeCursors(load_episode_cursors(room))
        # Message ids recorded this process lifetime, so a message recorded
        # twice (a retried request) lands once.
        self._ingested_ids: set[str] = set()

    def _persist_cursors(self) -> None:
        """Snapshot the delivery cursors to disk (best-effort, per mutation)."""
        write_cursors(self.room, self.log.cursors)

    def _persist_episode_cursors(self) -> None:
        """Snapshot the per-thread delivery positions to disk (best-effort)."""
        write_episode_cursors(self.room, self.episode_cursors.snapshot)

    def episode_position(self, handle: str, episode: str) -> int:
        """``handle``'s delivery position on ``episode``, forked off its room one."""
        return self.episode_cursors.position(handle, episode, default=self.log.position(handle))

    def advance_episode_cursor(self, handle: str, episode: str, pos: int) -> None:
        """Advance ``handle``'s durable position on ``episode`` and persist it."""
        self.episode_cursors.advance(handle, episode, pos, limit=len(self.log.records))
        self._persist_episode_cursors()

    def advance_cursor(self, handle: str, pos: int) -> None:
        """Advance ``handle``'s durable delivery cursor to ``pos`` and persist it.

        The consume side of the durable inbox for a server-held ``await`` caller:
        as ``await`` drains the transcript it commits the new position here so it
        survives a backend restart, rather than the process-local cursor that
        silently reset every handle to "now" on restart.
        """
        self.log.advance(handle, pos)
        self._persist_cursors()

    def rename_handle(self, old: str, new: str) -> None:
        """Move ``old``'s room and thread positions to ``new``."""
        self.log.rename(old, new)
        self.episode_cursors.rename(old, new)
        self._persist_cursors()
        self._persist_episode_cursors()

    def record(
        self, envelope: MyceliumMessage, content: dict[str, Any], *, list_write: bool = False
    ) -> None:
        """Record a message in the room: transcript, read positions, the app's
        live stream, and the trigger hooks. A message id already recorded this
        process lifetime is a no-op.

        ``list_write`` controls whether the message is also written to the
        in-memory list store: a person's message pre-writes nothing to
        ``in_memory_store`` (the transcript is its record, read back by
        :func:`conversational_messages`), while ``respond`` (``/reply``) passes
        ``list_write=True`` so an agent's turn is visible live, before a cold
        read re-projects the transcript.
        """
        mid = envelope_message_id(envelope)
        if mid is not None:
            if mid in self._ingested_ids:
                return
            self._ingested_ids.add(mid)
        record = record_from(envelope, content)
        self.log.record(record, recipients=envelope_recipients(envelope))
        append_transcript(self.room, record)
        self._persist_cursors()
        # The list store is the live/fast view; the durable transcript is the read
        # path's source of truth.
        if list_write:
            self._record_to_list_store(record)
        if self._feed_bus:
            self._publish_to_bus(record)
        if self.on_recorded is not None:
            try:
                self.on_recorded(record)
            except Exception:
                logger.exception("recorded hook failed for %s", record.message_id)
        # Triggers: who the message asks (``asks.py``, one rule for everyone).
        # A handle it mentions is summoned: an engine self-selects by its
        # manifest, so for anyone else that's a no-op. The full list goes to
        # every summon so an engine summoned alongside other handles
        # (``@conductor @a @b``) can bind those co-mentions to its roles.
        from app.services.asks import asked

        message_text = content.get("content", "") if isinstance(content, dict) else ""
        asking = asked(content, self.room)
        summons = [h for h, why in asking.items() if why != "turn"]
        for handle in summons:
            try:
                self.on_summon(handle, envelope, summons, message_text)
            except Exception:
                logger.exception("summon hook failed for @%s", handle)
        if self.on_asked is not None:
            for handle, why in asking.items():
                try:
                    self.on_asked(handle, why, envelope, message_text)
                except Exception:
                    logger.exception("asked hook failed for @%s", handle)

    def _publish_to_bus(self, record: TranscriptRecord) -> None:
        """Feed the recorded message to the in-process bus so the SSE UI sees it.

        The bus (``routes/stream.py``) is the frontend's live feed. Best-effort:
        never fail a record over a UI push.
        """
        try:
            from app.bus import bus, room_channel

            bus.publish(room_channel(self.room), bus_frame(self.room, record))
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
