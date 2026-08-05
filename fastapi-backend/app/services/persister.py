# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Backend-as-room-infrastructure: the persister / durable inbox (Step 4, bible §9).

Step 3 put the backend in every room's SLIM group channel as moderator but never
*read* the channel. Step 4 has the moderator consume it. This module is that
consumer, and it does four things as each message flows past:

1. **Persister.** Records the full transcript to the room's markdown (``log/``)
   so it survives, is git-shareable, and is picked up by the reindex watcher —
   memory the normal way (bible §11), a *distinct* artifact from the
   episode-scoped ``log/episodes/*`` records ``l9_episode`` writes.

2. **Durable inbox.** SLIM keeps **no** messages for an offline member (bible
   §7d): a broadcast that happened while a member was gone is never replayed on
   rejoin. So mycelium tracks each agent's delivery position (:class:`DeliveryLog`)
   and, when an agent **reconnects**, **re-serves** the tail it missed — targeted
   point-to-point (not a broadcast), so the rest of the room is untouched.

3. **Trigger-watcher (skeleton).** Recognizes ``@``-summon tokens in a message
   and calls a summon hook; the real cognition-engine wiring is Step 7. Here the
   hook defaults to a log.

4. **plan-compile hook (skeleton).** On a ``commit:converged`` envelope it fires
   a seam Step 8 will use to run ``plan_compiler``; it does **not** compile here.

The pure pieces (:class:`DeliveryLog`, the transcript read/write, the trigger
detection) carry no SLIM dependency and are unit-tested without a node;
:class:`RoomPersister` is the thin async loop that drives them over a live
:class:`~app.services.l9_slim.L9SlimChannel`.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services import l9

if TYPE_CHECKING:
    import slim_bindings

    from app.services.l9_models import L9
    from app.services.l9_slim import L9SlimChannel

logger = logging.getLogger(__name__)

# The transcript memory key under a room's dir (``log/transcript.md``). One
# jsonl-bearing markdown file per room: append-only, reindex-friendly, and
# deliberately separate from ``log/episodes/*`` (episode-scoped) so the two
# never clobber each other.
TRANSCRIPT_KEY = "log/transcript"

# An ``@``-summon token: ``@`` followed by a handle (letter/digit start, then
# word chars or hyphens). Guarded so it doesn't fire mid-word (e.g. an email).
_SUMMON_RE = re.compile(r"(?:^|(?<=[\s(<]))@([A-Za-z0-9][\w-]*)")


# ── Envelope helpers ─────────────────────────────────────────────────────────


def envelope_sender(envelope: L9) -> str | None:
    """The sending handle of an envelope (first actor), or None."""
    actors = envelope.header.participants.actors
    return actors[0].id if actors else None


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

    The backend's ``@``-parse (bible §12): map ``@agent-x`` tokens in a human's
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

    def __init__(self, records: list[TranscriptRecord] | None = None) -> None:
        self._records: list[TranscriptRecord] = list(records or [])
        self._cursors: dict[str, int] = {}

    @property
    def records(self) -> list[TranscriptRecord]:
        return list(self._records)

    def knows(self, handle: str) -> bool:
        """True once ``handle`` has ever been tracked (join or delivery)."""
        return handle in self._cursors

    def track(self, handle: str, *, caught_up: bool = True) -> None:
        """Register ``handle``. ``caught_up`` starts it at the transcript end
        (a first join missed nothing that preceded it); otherwise at the start."""
        if handle in self._cursors:
            return
        self._cursors[handle] = len(self._records) if caught_up else 0

    def record(self, record: TranscriptRecord, *, delivered_to: Iterable[str]) -> None:
        """Append ``record``; advance the cursor of every present member.

        A present member received the broadcast live, so its cursor moves to the
        new end. Absent members (not in ``delivered_to``) are left behind.
        """
        self._records.append(record)
        end = len(self._records)
        for handle in delivered_to:
            self._cursors[handle] = end

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

_TRANSCRIPT_HEADER = (
    "The live room transcript — every message recorded off the SLIM channel, "
    "one JSON record per line (distinct from the episode records under "
    "`log/episodes/`)."
)


def render_transcript(records: list[TranscriptRecord]) -> str:
    """The markdown body for the transcript file (a jsonl block)."""
    lines = [
        _TRANSCRIPT_HEADER,
        "",
        "```jsonl",
        *(json.dumps(r.to_json(), sort_keys=True) for r in records),
        "```",
        "",
    ]
    return "\n".join(lines)


def parse_transcript(body: str) -> list[TranscriptRecord]:
    """Parse the jsonl block of a transcript body back into records."""
    records: list[TranscriptRecord] = []
    in_block = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "```jsonl":
            in_block = True
            continue
        if stripped == "```":
            in_block = False
            continue
        if in_block and stripped:
            try:
                records.append(TranscriptRecord.from_json(json.loads(stripped)))
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("skipping malformed transcript line")
    return records


def load_transcript(room: str) -> list[TranscriptRecord]:
    """Read a room's persisted transcript (empty when none exists)."""
    from app.services.filesystem import get_room_dir, read_memory_file

    result = read_memory_file(get_room_dir(room), TRANSCRIPT_KEY)
    if result is None:
        return []
    _meta, body = result
    return parse_transcript(body)


def write_transcript(room: str, records: list[TranscriptRecord]) -> None:
    """Persist a room's transcript to ``log/transcript.md`` (best-effort)."""
    try:
        from app.services.filesystem import get_room_dir, write_memory_file

        base = get_room_dir(room)
        base.mkdir(parents=True, exist_ok=True)
        write_memory_file(
            base,
            TRANSCRIPT_KEY,
            render_transcript(records),
            created_by=l9.SYSTEM_ACTOR_ID,
            updated_by=l9.SYSTEM_ACTOR_ID,
        )
    except Exception:
        logger.exception("transcript write failed for room %s", room)


# ── The receive loop ─────────────────────────────────────────────────────────

SummonHook = Callable[[str, "L9"], None]
ConvergedHook = Callable[["L9"], None]

# Consecutive immediate transport failures before the loop gives up — keeps a
# torn-down channel from spinning a hot loop while tolerating transient hiccups.
_MAX_CONSECUTIVE_FAILURES = 3


def _default_summon_hook(handle: str, envelope: L9) -> None:
    logger.info("summon hook (skeleton): @%s summoned; engine wiring is Step 7", handle)


def _default_converged_hook(envelope: L9) -> None:
    logger.info(
        "plan-compile hook (skeleton): commit:converged on episode %s; "
        "plan_compiler wiring is Step 8",
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
        feed_bus: bool = True,
    ) -> None:
        self.room = room
        self._channel = channel
        self._members_provider = members_provider
        self.on_summon = on_summon or _default_summon_hook
        self.on_converged = on_converged or _default_converged_hook
        self._feed_bus = feed_bus
        # Resume from the persisted transcript so cursors/re-serve survive a
        # backend restart (records already on disk count as history).
        self.log = DeliveryLog(load_transcript(room))
        # handle -> most recent inbound MessageContext, for targeted re-serve.
        self._contexts: dict[str, slim_bindings.MessageContext] = {}
        # Message ids ingested this process lifetime, so a message the backend
        # publishes itself (the human proxy, Step 6) is recorded/fed to the bus
        # exactly once even if SLIM loops the broadcast back to the moderator.
        self._ingested_ids: set[str] = set()

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
        return False

    async def reserve(self, handle: str) -> int:
        """Re-serve ``handle`` the messages it missed while offline, in order.

        Targeted (point-to-point) so the rest of the room is untouched. Requires
        a cached reply context for ``handle`` (from an earlier message it sent);
        without one there is no route to re-serve to, so it is a no-op until the
        connector holds its own identity (Step 5). Returns the count re-served.
        """
        missed = self.log.undelivered(handle)
        if not missed:
            return 0
        context = self._contexts.get(handle)
        if context is None:
            logger.debug("no reply context for %s; cannot re-serve %d missed", handle, len(missed))
            return 0
        served = 0
        for record in missed:
            try:
                await self._channel.send_content_to(context, record.content)
                served += 1
            except Exception:
                logger.exception("re-serve to %s failed at message %s", handle, record.message_id)
                break
        if served:
            self.log.mark_caught_up(handle)
            logger.info(
                "re-served %d missed message(s) to %s in room %s", served, handle, self.room
            )
        return served

    # -- the loop --

    async def run(self) -> None:
        """Pull from the channel forever, recording and dispatching each message."""
        failures = 0
        while True:
            try:
                released, arrived, context = await self._channel.receive_with_context()
            except Exception as exc:
                from asyncio import CancelledError

                if isinstance(exc, CancelledError):
                    raise
                failures += 1
                logger.debug(
                    "persister receive error on room %s (%d): %s", self.room, failures, exc
                )
                if failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.info("persister for room %s stopping after repeated errors", self.room)
                    return
                continue
            failures = 0
            # Cache the arrived sender's reply context for future re-serve.
            sender = envelope_sender(arrived)
            if sender is not None:
                self._contexts[sender] = context
            for envelope, content in released:
                self._ingest(envelope, content)

    def ingest_local(self, envelope: L9, content: dict[str, Any]) -> None:
        """Ingest a message the moderator published itself (the human proxy).

        The backend speaks for the human on the fabric (bible §12): it publishes
        the human's ``exchange`` on the channel *and* records it here directly, so
        the transcript and UI bus see it regardless of whether SLIM delivers a
        broadcast back to its own sender. :meth:`_ingest` de-dupes by message id,
        so a loopback of the same broadcast is a no-op.
        """
        self._ingest(envelope, content)

    def _ingest(self, envelope: L9, content: dict[str, Any]) -> None:
        mid = envelope_message_id(envelope)
        if mid is not None:
            if mid in self._ingested_ids:
                return
            self._ingested_ids.add(mid)
        record = record_from(envelope, content)
        present = set(self._members_provider())
        self.log.record(record, delivered_to=present)
        write_transcript(self.room, self.log.records)
        if self._feed_bus:
            self._publish_to_bus(record)
        # Triggers: @-summon and commit:converged (skeleton hooks).
        for handle in find_summons(content):
            try:
                self.on_summon(handle, envelope)
            except Exception:
                logger.exception("summon hook failed for @%s", handle)
        if is_converged(envelope):
            try:
                self.on_converged(envelope)
            except Exception:
                logger.exception("converged hook failed")

    def _publish_to_bus(self, record: TranscriptRecord) -> None:
        """Feed the recorded message to the in-process bus so the SSE UI sees it.

        The bus (``routes/stream.py``) is the frontend's live feed until Step 10;
        agent messages arrive over SLIM, not HTTP, so the persister is what keeps
        that feed fed. Best-effort — never fail a record over a UI push.
        """
        try:
            from app.bus import bus, room_channel

            payload = {
                "id": record.message_id,
                "sender_handle": record.sender or l9.SYSTEM_ACTOR_ID,
                "message_type": f"l9_{record.kind}",
                "content": json.dumps(record.content),
                "created_at": record.recorded_at,
                "room_name": self.room,
            }
            bus.publish(room_channel(self.room), payload)
        except Exception:
            logger.debug("bus publish from persister failed for room %s", self.room, exc_info=True)
