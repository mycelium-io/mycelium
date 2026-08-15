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
   ``on_converged`` seam the plan-sync consumer runs ``plan_compiler`` off of;
   the persister itself does **not** compile — it just fires the seam.

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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.schemas import MessageType
from app.services import l9
from app.services.l9_slim import ChannelReceiveTimeout

# Stable namespace so a transcript record maps to the same synthetic
# ``StoredMessage.id`` on every read (the envelope id is the seed).
_MESSAGE_ID_NS = uuid.UUID("6f1d2c3b-4a59-6e7d-8c9b-0a1b2c3d4e5f")

if TYPE_CHECKING:
    import slim_bindings

    from app.services.l9_models import L9
    from app.services.l9_slim import L9SlimChannel
    from app.services.local_state import StoredMessage

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


def stored_message_from_record(room: str, record: TranscriptRecord) -> StoredMessage | None:
    """Project a transcript record into the ``StoredMessage`` the list/UI reads.

    Returns None for a non-conversational record. The synthetic id is derived from
    the envelope id so it's stable across reads, and ``message_id`` carries that
    envelope id as the cross-store correlation key (dedup against ``local_state``).
    """
    from app.services.local_state import StoredMessage

    text = _conversational_text(record.content)
    if text is None:
        return None
    episode = record.content.get("l9", {}).get("header", {}).get("message", {}).get("episode")
    seed = record.message_id or f"{record.recorded_at}:{record.sender}"
    msg = StoredMessage(
        room_name=room,
        sender_handle=record.sender,
        message_type=MessageType.BROADCAST,
        content=text,
        episode=episode if isinstance(episode, str) else None,
        message_id=record.message_id or None,
        id=uuid.uuid5(_MESSAGE_ID_NS, seed),
    )
    with contextlib.suppress(ValueError, TypeError):
        msg.created_at = datetime.fromisoformat(record.recorded_at)
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


def conversational_messages(room: str) -> list[StoredMessage]:
    """The room's conversational history, projected from the durable transcript.

    The read path's source of truth for chat: it survives restarts (the transcript
    is on disk) and both post paths converge here (``respond`` and a human
    broadcast both land in the transcript). Event-ledger rows live only in
    ``local_state`` and are merged in by the route.
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
    messages = [
        m for r in load_transcript(room) if (m := stored_message_from_record(room, r)) is not None
    ]
    _conversational_cache[room] = (stamp, messages)
    return list(messages)


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
    # tests / a bare backend). In the running backend ``main.py`` binds this to
    # the plan-sync consumer via the manager's ``_converged_adapter``.
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
        # Health counters surfaced via RoomChannelManager.status(). ``receive_errors``
        # is genuine (fatal) transport faults; ``transient_errors`` is recoverable
        # membership-churn receive errors (retried, not lost) — split so the health
        # surface distinguishes "the channel is faulting" from "the channel is
        # churning". ``reserve_failures``/``reserve_skipped`` make the two ways a
        # missed-message re-serve fails to land visible instead of log-only.
        self.reserves = 0
        self.receive_errors = 0
        self.transient_errors = 0
        self.reserve_failures = 0
        self.reserve_skipped = 0

    def _persist_cursors(self) -> None:
        """Snapshot the delivery cursors to disk (best-effort, per mutation)."""
        write_cursors(self.room, self.log.cursors)

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
        ``local_state`` (the transcript is its record, read back by
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
        # The list store is the live/fast lens; the durable transcript is the read
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
        """Mirror a conversational record into the in-memory list store (live lens).

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
            from app.services import local_state

            local_state.add_message(self.room, msg)
        except Exception:
            logger.debug("list-store write failed for room %s", self.room, exc_info=True)
