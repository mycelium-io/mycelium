# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Each room's channel on the hub: its log, who is present, and its threads.

A room's channel is the room's timeline, kept by the hub. Every message is
recorded by the room's :class:`~app.services.persister.RoomPersister` (its
transcript, each member's read position, and the ``@``-summon and wake
triggers), fed to the app's live stream, and read by agents with ``await``.
This registry holds one per room, opened on first use, along with presence
(``await`` leases and herdr), the herdr wake queue, the episode a negotiation
freezes its parties for (a party leaving aborts it; the channel, and any task
the negotiation was happening inside, are untouched), and the floors held in
threads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services import groups, message_format
from app.services.agent_registry import norm_handle
from app.services.episode_lifecycle import EpisodeLifecycle, build_episode_abort_envelope
from app.services.floor import Floor
from app.services.message_format import serialize_content
from app.services.message_models import Kind
from app.services.persister import (
    AskedHook,
    RoomPersister,
    SummonHook,
    TranscriptRecord,
    envelope_message_id,
    envelope_sender,
    parse_mentions,
    record_episode,
)

if TYPE_CHECKING:
    from app.services.message_models import MyceliumMessage

# The room-aware summon hook the manager holds: unlike the persister's
# per-message ``SummonHook`` (which knows only the handle + envelope), this
# carries the ``room`` so the engines wired to it know which channel the
# summon came from. ``_start_persister`` adapts it down to the persister's
# signature by binding the room.
RoomSummonHook = Callable[[str, str, "MyceliumMessage", list[str], str], None]

# The room-aware turn hook: ``(room, handle, envelope, message_text)`` for each
# handle a message put a turn to (:mod:`app.services.asks`), the way the conductor
# and the conductor ask one member. The members the hub plays answer it.
RoomTurnHook = Callable[[str, str, "MyceliumMessage", str], None]
# The board-event hook: ``(room, data)`` for every notice raised, where ``data``
# is the notice's payload (``subkind``, ``key``, ``title``, ``episode``, ``by``,
# and ``for`` on a ``filed`` row given to someone).
RoomNoticeHook = Callable[[str, dict[str, str]], None]
# The every-message hook: ``(room, record)`` once per message the room records,
# after it is durable. The verifier reads agents' prose off it.
RoomRecordedHook = Callable[[str, "TranscriptRecord"], None]

logger = logging.getLogger(__name__)

#: How a held wake's reason ranks when another wake for the same handle
#: arrives: something it subscribed to least, so it never replaces an ask,
#: then a text mention, a turn put to it, a task given to it or its schedule
#: above that, and an interrupt above those. A resume outranks everything: its
#: digest covers whatever else was asked while the agent was paused. A reason
#: not listed ranks with a turn.
WAKE_RANK = {
    "subscribed": -1,
    "mention": 0,
    "turn": 1,
    "assigned": 1,
    "handback": 1,
    "schedule": 1,
    "interrupt": 2,
    "resumed": 3,
}

# The hub's own handle in a room. Distinct from any real agent handle so it
# never collides with a participant, and never treated as one.
BACKEND_AGENT = "backend"

# Who a room has announced as joined, kept beside its memories so a join is
# said once per member, not again after every restart.
ANNOUNCED_FILENAME = ".announced.json"


def _announced_path(room: str):
    """The room's announced-members file, or None when the room has no folder."""
    from app.services.filesystem import room_path

    room_dir = room_path(room)
    return room_dir / ANNOUNCED_FILENAME if room_dir.is_dir() else None


def _load_announced(room: str) -> set[str]:
    path = _announced_path(room)
    if path is None:
        return set()
    try:
        handles = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {h for h in handles if isinstance(h, str)} if isinstance(handles, list) else set()


def _save_announced(room: str, handles: set[str]) -> None:
    path = _announced_path(room)
    if path is None:
        return
    try:
        path.write_text(json.dumps(sorted(handles)), encoding="utf-8")
    except OSError:
        # Best-effort: at worst a restart announces a member once more.
        logger.debug("could not record announced members for room %s", room)


def _is_own_registered_agent(room: str, handle: str) -> bool:
    """True if ``handle`` is an agent registered in ``room`` (manifest on disk).

    Its manifest lives at ``agents/{handle}.md`` in the room dir. This is what
    separates an ``@``-mention that should pull someone onto the channel from one
    that is only addressing a human, or a handle nobody registered.
    """
    from app.services.filesystem import get_room_dir

    return (get_room_dir(room) / "agents" / f"{handle}.md").exists()


def _registered_kind(room: str, handle: str) -> str | None:
    """The engine kind ``handle``'s manifest in ``room`` names, or ``None``."""
    from app.services.engine_kinds import registered_engine_kind

    return registered_engine_kind(room, handle)


def _is_engine(room: str, handle: str) -> bool:
    """True if ``handle``'s manifest in ``room`` names an engine kind."""
    return _registered_kind(room, handle) is not None


def _registered_agent_handles(room: str) -> list[str]:
    """Every agent handle with a manifest in ``room`` (``agents/*.md`` stems)."""
    from app.services.filesystem import get_room_dir

    agents_dir = get_room_dir(room) / "agents"
    if not agents_dir.is_dir():
        return []
    return sorted(p.stem for p in agents_dir.glob("*.md"))


@dataclass
class ManagedRoomChannel:
    """One room's channel: its log, and the episode and floors held in it."""

    room: str
    persister: RoomPersister
    lifecycle: EpisodeLifecycle = field(default_factory=EpisodeLifecycle)
    # Threads whose floor a run of backend code holds, keyed by episode URN
    # (:mod:`app.services.floor`). Independent of ``lifecycle``: a negotiation
    # freezes a roster, a floor names whose turn it is, and a room may hold
    # several floors at once, one per thread a protocol is running in.
    floors: dict[str, Floor] = field(default_factory=dict)

    async def post(self, envelope: MyceliumMessage, text: str, *, list_write: bool = False) -> None:
        """Record *envelope* with ``text`` as its content.

        The caller builds the message (kind, recipients and payload vary per
        call site); this records it. ``list_write`` is passed through to
        ``persister.record``: ``True`` for agent replies that must appear in
        the in-memory store list, ``False`` for broker messages that ride the
        transcript only.
        """
        content = serialize_content(envelope, extra={"content": text})
        self.persister.record(envelope, content, list_write=list_write)


@dataclass
class HumanPublishResult:
    """The outcome of recording a person's message in a room.

    ``recipients`` are the message recipients the ``@``-parse resolved (present members
    that get woken).
    """

    mentioned: list[str]
    recipients: list[str]
    # Handles that were @-mentioned but are neither present in the room nor a
    # registered agent — they received no delivery and triggered no action.
    unrecognized: list[str] = field(default_factory=list)
    # The published envelope's message id — the correlation key the POST route
    # stamps on its ``in_memory_store`` row so a cold read from the durable transcript
    # dedups against it instead of showing the human's message twice.
    message_id: str | None = None


@dataclass
class MemberPresence:
    """How a present room member is connected, for the presence surface.

    ``kind`` is ``"lease"`` (server-held ``await``/``reply`` poll) or
    ``"herdr"`` (alive in a herdr-managed pane but not currently joined, pushed
    by the host-side ``mycelium herdr sync`` bridge, since the backend is
    containerized and herdr-blind). ``last_seen`` is the wall-clock epoch of
    the member's most recent poll/sync. ``status`` carries herdr's live agent
    state (``idle``/``working``/``blocked``/``done``), set on a herdr member,
    or overlaid onto a lease member that is *also* mapped to a live herdr pane. ``wake_pending`` is True when a room mention
    is queued for this handle but held back until it goes idle (the hold-until-idle
    doorbell), so the UI can show "tagged, waking when free".
    """

    kind: str
    last_seen: float | None = None
    status: str | None = None
    wake_pending: bool = False
    # herdr's terminal title — the agent's current task ("Review PR 540 comments").
    # Pushed by the sync bridge; surfaced as the roster's activity line.
    title: str | None = None


class RoomChannelManager:
    """Registry of room channels (one per room, per process)."""

    def __init__(self) -> None:
        self._channels: dict[str, ManagedRoomChannel] = {}
        # Strong refs to in-flight background work (notices raised from sync callers).
        self._tasks: set[asyncio.Task[object]] = set()
        # Trigger hooks handed to every persister, both room-aware and wired at
        # startup (``main.py``): ``on_summon`` → every engine's
        # ``handle_summon``. Unset → the persister's log-only default.
        self.on_summon: RoomSummonHook | None = None
        self.on_turn: RoomTurnHook | None = None
        # Fired after every notice, so something that acts on the board (the
        # worker engine, the herdr doorbell) hears it move without polling it.
        # A notice still wakes no ``await``; this is an in-process listener.
        self.on_notice: RoomNoticeHook | None = None
        # Fired for every recorded message, so something that reads the room as
        # it goes (the verifier) doesn't poll the transcript. Wakes nobody.
        self.on_recorded: RoomRecordedHook | None = None
        # Server-held presence: a handle that participates over HTTP (the CLI
        # ``await``/``respond`` long-poll) holds no connection between turns, so
        # the backend keeps it "present" via a lease (room → handle → monotonic
        # expiry), refreshed on every await/reply, and ``members`` lists it so an
        # engine's roster includes it.
        self._leases: dict[str, dict[str, float]] = {}
        # Wall-clock epoch of each handle's most recent await/reply, keyed like
        # ``_leases``. Monotonic time drives expiry (skew-proof); this parallel
        # wall-clock stamp is only for surfacing "last seen 5s ago" in the UI.
        self._last_seen: dict[str, dict[str, float]] = {}
        # Which handles have had a coordination_join notice in each room: a join is
        # a member's first arrival, not every return from a lapsed lease or a
        # reconnect. Loaded from and kept in the room's folder
        # (``ANNOUNCED_FILENAME``), so a restart doesn't re-announce everyone;
        # only removing a member from the room forgets them.
        self._announced: dict[str, set[str]] = {}
        # herdr liveness overlay: room → handle → (status, title, monotonic expiry,
        # wall-clock last_seen). ``title`` is herdr's terminal title (the agent's
        # current task). Pushed by the host-side `mycelium herdr sync` bridge (the
        # backend can't see the host's herdr socket). Purely a presence/UI surface —
        # it never enters `members()` (the engines' roster), so a herdr-alive-but-
        # not-joined agent is *visible* without being made a negotiation participant.
        # Entries lapse on their TTL if sync stops. Kept per source (the machine
        # that pushed them), so one machine's push never removes another's
        # agents: room → source → handle → (status, title, expires, last_seen).
        self._herdr: dict[
            str, dict[str, dict[str, tuple[str | None, str | None, float, float]]]
        ] = {}
        # herdr wake queue: room → list of pending {handle, ts} "doorbells". A tag
        # of a herdr-present handle enqueues one entry (deduped by handle — the
        # wake is a nudge, not a payload; the agent reads the room itself, so extra
        # tags don't add information). The backend is herdr-blind, so it enqueues
        # here and the host-side `herdr sync` bridge drains + runs the actual
        # `herdr agent prompt`. The "commands down" half of the bidirectional bridge.
        self._herdr_wakes: dict[str, list[dict]] = {}

    def get(self, room: str) -> ManagedRoomChannel | None:
        """The room's channel, opened on first use; ``None`` for a room the hub
        has no folder for."""
        existing = self._channels.get(room)
        if existing is not None:
            return existing
        from app.services.filesystem import room_path

        if not room_path(room).is_dir():
            return None
        return self.open(room)

    def open(self, room: str) -> ManagedRoomChannel:
        """Open (idempotently) the channel for ``room``: its log, read back
        from the room's transcript and read positions on disk."""
        existing = self._channels.get(room)
        if existing is not None:
            return existing
        managed = ManagedRoomChannel(
            room=room,
            persister=RoomPersister(
                room,
                on_summon=self._summon_adapter(room),
                on_asked=self._asked_adapter(room),
                on_recorded=self._recorded_adapter(room),
            ),
        )
        self._channels[room] = managed
        return managed

    async def provision(self, room: str) -> ManagedRoomChannel:
        """:meth:`open`, for the async callers that set a room up."""
        return self.open(room)

    def members(self, room: str) -> list[str]:
        """Agent handles present in ``room``: those holding an ``await`` lease.

        A turn-based agent (HTTP ``await`` long-poll) is present through its
        lease; the engines' roster is this list.
        """
        return sorted(self._live_leases(room))

    def presence(self, room: str) -> dict[str, MemberPresence]:
        """Live presence breakdown: handle → :class:`MemberPresence` per member.

        ``await``/``reply`` lease members first, with ``last_seen`` their most
        recent poll time, then herdr's agents overlaid.
        """
        seen = self._last_seen.get(room, {})
        out: dict[str, MemberPresence] = {
            h: MemberPresence(kind="lease", last_seen=seen.get(h)) for h in self._live_leases(room)
        }
        # Overlay herdr liveness: a handle already present (lease) just gains
        # its herdr ``status``; a herdr-only handle appears as ``kind="herdr"`` so
        # the UI can surface "alive in herdr, not joined" without it becoming a
        # roster member.
        for h, (status, title, last_seen) in self._live_herdr(room).items():
            if h in out:
                out[h].status = status
                out[h].title = title
            else:
                out[h] = MemberPresence(
                    kind="herdr", last_seen=last_seen, status=status, title=title
                )
        # Overlay held doorbells: a mention queued for a handle that hasn't gone
        # idle yet. Surface it even on a handle with no other presence (its herdr
        # overlay may have lapsed while the wake is still held) so the tag stays
        # visible until it lands.
        for h in self.pending_herdr_wakes(room):
            if h in out:
                out[h].wake_pending = True
            else:
                out[h] = MemberPresence(kind="herdr", wake_pending=True)
        return out

    def _live_by_source(
        self, room: str
    ) -> dict[str, dict[str, tuple[str | None, str | None, float]]]:
        """Unexpired herdr presence for ``room`` by source: source → handle →
        (status, title, last_seen).

        Opportunistically drops lapsed entries, and sources left with none, so a
        handle whose sync stopped (herdr closed, runner stopped) disappears from
        the surface on its own.
        """
        now = time.monotonic()
        sources = self._herdr.get(room)
        if not sources:
            return {}
        live: dict[str, dict[str, tuple[str | None, str | None, float]]] = {}
        kept: dict[str, dict[str, tuple[str | None, str | None, float, float]]] = {}
        for source, entries in sources.items():
            fresh = {h: e for h, e in entries.items() if e[2] > now}
            if fresh:
                kept[source] = fresh
                live[source] = {h: (s, t, seen) for h, (s, t, _exp, seen) in fresh.items()}
        self._herdr[room] = kept
        return live

    def _live_herdr(self, room: str) -> dict[str, tuple[str | None, str | None, float]]:
        """Unexpired herdr presence for ``room``, merged across the machines that
        push it: handle → (status, title, last_seen). A handle more than one
        machine reports takes the most recent report."""
        merged: dict[str, tuple[str | None, str | None, float]] = {}
        for entries in self._live_by_source(room).values():
            for handle, entry in entries.items():
                if handle not in merged or entry[2] > merged[handle][2]:
                    merged[handle] = entry
        return merged

    def set_herdr_presence(
        self,
        room: str,
        statuses: dict[str, str | dict],
        *,
        ttl_s: float = 90.0,
        source: str = "",
    ) -> None:
        """Replace ``source``'s herdr liveness for ``room`` (a sync bridge's push).

        ``statuses`` maps handle → herdr agent state, either a bare status string or
        ``{"status": ..., "title": ...}`` (the title is herdr's terminal title, the
        agent's current task). Each entry is stamped with a fresh ``ttl_s`` expiry; a
        handle omitted from a later push lapses on its own once its TTL elapses (so a
        closed pane clears without an explicit delete).

        A push is the full current view of the machine that sent it, so it
        replaces that ``source``'s entries and no other's: two machines' agents
        in one room are both present, whichever pushed last. A bridge that names
        no source shares the one ``""`` source with any other that doesn't.
        """
        now_m = time.monotonic()
        now_w = time.time()
        overlay: dict[str, tuple[str | None, str | None, float, float]] = {}
        for handle, value in statuses.items():
            if isinstance(value, dict):
                status = value.get("status")
                title = value.get("title")
            else:
                status, title = value, None
            overlay[handle] = (status, title, now_m + ttl_s, now_w)
        self._herdr.setdefault(room, {})[source] = overlay

    def herdr_status(self, room: str, handle: str) -> str | None:
        """The live herdr state for ``handle`` in ``room``, or ``None`` if not
        herdr-present. Used to decide whether a mention should enqueue a wake."""
        return self._live_herdr(room).get(handle, (None,))[0]

    def herdr_handles_from(self, room: str, source: str) -> set[str]:
        """The handles ``source``'s latest push reports live in ``room``: the
        agents whose panes that machine holds."""
        return set(self._live_by_source(room).get(source, {}))

    def enqueue_herdr_wake(
        self,
        room: str,
        handle: str,
        *,
        reason: str = "mention",
        key: str | None = None,
        title: str | None = None,
        sender: str | None = None,
        episode: str | None = None,
        why: str | None = None,
        message: str | None = None,
        interrupted: str | None = None,
    ) -> None:
        """Ring the doorbell for a herdr-present handle in ``room``.

        Enqueued regardless of the agent's current state — a tag for a *busy*
        agent is **held** here and released once it goes idle (see
        :meth:`drain_herdr_wakes`), so the nudge is never lost just because the
        agent was mid-turn. Deduped by handle: repeated tags collapse to one
        pending nudge, refreshing its hold timer and counting how many there
        were. The agent still reads the room itself (``await`` hands it the
        message and everything said since its last turn).

        ``reason`` says what kind of doorbell it is, so the bridge can word the
        prompt: ``mention`` (someone tagged you), ``turn`` (a turn is addressed
        to you), ``assigned`` (the row ``key`` was given to you), or
        ``interrupt`` (an ``@!`` stopped your turn to say this), or
        ``subscribed`` (something it subscribed to happened; ``why`` says which
        subscription and what). The most specific reason pending wins over a
        mention, and an interrupt over the rest, since the agent's turn was
        stopped to deliver it; a subscription never replaces any of them.

        ``sender`` and ``episode`` say who rang last and where. What they said
        isn't kept here: when the wake is delivered, the digest it carries is
        built from the transcript then (``wake_digest``), so it is current.
        ``message`` is the wire id of the message that rang, kept with every
        other that rang the same pending wake, so a sender can tell whether
        their message is still waiting to be read (:meth:`held_for`).
        ``interrupted`` is the message an interrupt was made with after it was
        sent (``interrupts.upgrade``), which the digest says.
        """
        queue = self._herdr_wakes.setdefault(room, [])
        entry: dict = {"handle": handle, "ts": time.monotonic(), "reason": reason}
        if key:
            entry["key"] = key
        if title:
            entry["title"] = title
        if sender:
            entry["from"] = sender.lstrip("@")
        if episode:
            entry["episode"] = episode
        if why:
            entry["why"] = why
        if interrupted:
            entry["interrupted"] = interrupted
        for w in queue:
            if w["handle"] == handle:
                w["ts"] = entry["ts"]  # fresh activity refreshes the hold timer
                if message and message not in w.setdefault("messages", []):
                    w["messages"].append(message)
                if reason == "interrupt" and not interrupted:
                    # A fresh `@!` is what this interrupt is now, not a sent one.
                    w.pop("interrupted", None)
                # The reason only moves up: a turn or an assignment outranks a
                # mention, and an interrupt outranks them all. Who rang and
                # where move with it, so a wake never names the sender of a
                # lesser one: an interrupt from a person stays theirs when an
                # agent mentions the same handle after it.
                if WAKE_RANK.get(reason, 1) >= WAKE_RANK.get(w.get("reason", "mention"), 1):
                    # A subscription's why belongs to it alone; an ask that
                    # replaces it doesn't carry it on.
                    w.pop("why", None)
                    w.update({k: v for k, v in entry.items() if k != "handle"})
                return
        # Its id follows it to the runner and back, so the wake log
        # (:mod:`app.services.wake_log`) records it once, with its outcome.
        entry["id"] = secrets.token_hex(6)
        if message:
            entry["messages"] = [message]
        queue.append(entry)

    def held_for(self, room: str, handle: str, message: str) -> bool:
        """Whether ``handle``'s wake for the message with wire id ``message`` is
        still held: queued, not yet handed to its runner. Once it's handed over
        the agent has the message, so there's nothing left to bring forward."""
        return any(
            w["handle"] == handle and message in w.get("messages", [])
            for w in self._herdr_wakes.get(room, [])
        )

    def ring_asked(
        self,
        room: str,
        handle: str,
        reason: str,
        *,
        sender: str | None = None,
        episode: str | None = None,
        message: str | None = None,
    ) -> bool:
        """Ring the herdr doorbell of a handle a message just asked for something.

        Who was asked, and why, is :mod:`app.services.asks`'s to say; every
        message recorded in a room is held to it on the way in
        (``persister`` → :meth:`_asked_adapter`), whichever path wrote it, so a
        mention from the app, from ``respond``, from a worker or from an engine
        rings the same way. A handle with no herdr pane isn't rung; a
        registered agent that nothing is running is logged as unreached.
        ``True`` when a wake was queued.

        An ``interrupt`` also stops a working agent's turn, when the sender may
        (:mod:`app.services.interrupts`); otherwise it rings as a ``mention``.
        """
        name = handle.lstrip("@").lower()
        if ":" in name:
            # A subagent has no doorbell; the same message asks its parent,
            # which is rung for it (``asks``).
            return False
        status = self.herdr_status(room, name)
        if status is None:
            if self._unreachable_agent(room, name):
                from app.services import wake_log

                # Not lost: the agent reads it on its next `await`. Nothing
                # could be woken with it now, which is what the log says.
                wake_log.dropped(
                    room,
                    {"handle": name, "reason": reason, "from": sender, "episode": episode},
                    "nothing is running it: no herdr pane reports it and it isn't awaiting",
                    outcome="unreached",
                )
            return False
        if reason == "interrupt":
            from app.services import interrupts, pauses

            # A paused agent stays paused: the @! waits for its resume like
            # any other ask.
            if pauses.is_paused(room, name) or not interrupts.request(room, name, sender, status):
                reason = "mention"
        self.enqueue_herdr_wake(
            room, name, reason=reason, sender=sender, episode=episode, message=message
        )
        return True

    def ring_subscribed(self, room: str, record: TranscriptRecord) -> list[str]:
        """Ring the doorbell of each herdr-present handle ``record`` falls under
        a subscription of, and end the task subscriptions it finished.

        Every recorded message is held to the room's subscriptions on the way
        in (:meth:`_recorded_adapter`), as it is to :mod:`app.services.asks`; a
        handle the record asks is rung for that instead (:meth:`ring_asked`),
        so this rings only the rest, ranked below any ask. A handle with no
        herdr pane reads it on its next ``await``. Returns who was rung.
        """
        from app.services import subscriptions
        from app.services.asks import woken_by

        # Whoever its sender was answering, stamped now: ``await`` reads it
        # later, when that turn may be over.
        subscriptions.note_posted(room, record)
        subs = subscriptions.load(room)
        if not subs:
            return []
        rung: list[str] = []
        for handle, wake in woken_by(room, record).items():
            if wake.reason != "subscribed" or self.herdr_status(room, handle) is None:
                continue
            self.enqueue_herdr_wake(
                room,
                handle,
                reason="subscribed",
                sender=record.sender,
                episode=record_episode(record),
                why=wake.why,
            )
            rung.append(handle)
        subscriptions.end_settled(room, record)
        return rung

    def _unreachable_agent(self, room: str, handle: str) -> bool:
        """Whether ``handle`` is a registered agent that a mention can't reach
        right now: no herdr pane reports it and it holds no ``await`` lease. A
        person or an engine is reached some other way, and isn't one."""
        from app.services.principals import classify_sender

        if classify_sender(room, handle) != "agent":
            return False
        return handle not in self.members(room)

    def herdr_wake_assigned(self, room: str, notice: dict[str, str]) -> bool:
        """Ring the herdr-present handle a newly filed row was given to.

        A ``filed`` notice carrying ``for`` is a row put on the board for
        someone; if that someone lives in herdr, they hear about it now rather
        than on their next look at the board. ``True`` when a wake was queued.
        """
        if notice.get("subkind") != "filed" or not notice.get("for"):
            return False
        name = str(notice["for"]).lstrip("@").lower()
        if self.herdr_status(room, name) is None:
            return False
        self.enqueue_herdr_wake(
            room,
            name,
            reason="assigned",
            key=notice.get("key"),
            title=notice.get("title"),
            sender=notice.get("by"),
        )
        return True

    def pending_herdr_wakes(self, room: str, *, hold_ttl_s: float = 600.0) -> set[str]:
        """Handles with a queued (not-yet-delivered) wake in ``room`` — read-only.

        The non-destructive counterpart to :meth:`drain_herdr_wakes`: it peeks the
        hold queue for the presence surface without releasing anything, so the UI
        can badge a tagged-but-busy agent. A wake older than ``hold_ttl_s`` for
        an agent no herdr pane reports is excluded, matching what drain would drop.
        """
        queue = self._herdr_wakes.get(room)
        if not queue:
            return set()
        now = time.monotonic()
        live = self._live_herdr(room)
        return {
            w["handle"]
            for w in queue
            if w["handle"] in live or now - float(w.get("ts", now)) <= hold_ttl_s
        }

    def drain_herdr_wakes(
        self, room: str, *, hold_ttl_s: float = 600.0, source: str | None = None
    ) -> list[dict]:
        """Release wakes for handles that are **currently idle**; hold the rest.

        The "agent hold": a queued wake is returned to the bridge only once herdr
        shows its handle ``idle``/``done`` (ready to take a turn). A ``working``/
        ``blocked`` handle keeps its wake queued until it frees up, however long
        its turn runs: a mention for an agent on a long task reaches it when the
        task ends, not never. A wake is dropped only once it's older than
        ``hold_ttl_s`` and no herdr pane reports its agent any more, so nothing
        is left to deliver it to. Presence is refreshed by the sync bridge every
        few seconds, so the backend's view of "idle" is near-live.

        A paused agent's wake is held whatever its state and however long, and
        never dropped: its resume (``reason="resumed"``) takes its place, and
        that digest covers everything that arrived during the pause.

        With ``source``, only wakes for handles that machine's own push reports
        are released: the others are held for the machine whose panes they are,
        so a runner never takes a wake it can't deliver. With none (a bridge
        that names no source), any wake is released, as before.
        """
        queue = self._herdr_wakes.get(room)
        if not queue:
            return []
        from app.services import pauses

        now = time.monotonic()
        live = self._live_herdr(room)
        mine = self.herdr_handles_from(room, source) if source is not None else None
        paused = pauses.paused_in(room)
        released: list[dict] = []
        held: list[dict] = []
        for w in queue:
            status = live.get(w["handle"], (None,))[0]
            if w["handle"] in paused:
                held.append(w)
                continue
            if status is None and now - float(w.get("ts", now)) > hold_ttl_s:
                # Nothing reports the agent any more: dropped, and said why.
                from app.services import wake_log

                minutes = round(hold_ttl_s / 60)
                why = (
                    f"held {minutes} min with no herdr pane reporting it "
                    "(no runner syncing this room)"
                )
                wake_log.dropped(room, w, why)
                continue
            if mine is not None and w["handle"] not in mine:
                held.append(w)  # another machine's agent: that runner takes it
                continue
            if status in {"idle", "done", "unknown"}:
                released.append(w)
            else:  # working/blocked (or presence briefly gone) → keep holding
                held.append(w)
        self._herdr_wakes[room] = held
        return released

    def _live_leases(self, room: str) -> set[str]:
        """Handles with an unexpired presence lease in ``room``."""
        now = time.monotonic()
        leases = self._leases.get(room)
        if not leases:
            return set()
        live = {h for h, exp in leases.items() if exp > now}
        # Opportunistically drop expired leases so the map doesn't grow forever.
        # A lapsed lease is an agent between turns, not one that left, so its
        # return is not announced again.
        expired = set(leases) - live
        if expired:
            self._leases[room] = {h: leases[h] for h in live}
            seen = self._last_seen.get(room)
            if seen:
                for h in expired:
                    seen.pop(h, None)
        return live

    def refresh_lease(self, room: str, handle: str, ttl_s: float = 180.0) -> None:
        """Mark ``handle`` server-held-present in ``room`` for ``ttl_s`` seconds.

        Called on every ``await``/``reply`` so an actively-participating agent stays
        in the roster; a generous TTL keeps it present through its own think time
        (and avoids a mid-episode membership flap) while a truly-gone agent lapses.
        The not-present → present edge is a join: it emits a coordination_join
        notice. It never touches a running negotiation, which only a party
        leaving the room ends (:meth:`_abort_if_party_left`).
        """
        was_present = handle in self._live_leases(room)
        self._leases.setdefault(room, {})[handle] = time.monotonic() + ttl_s
        self._last_seen.setdefault(room, {})[handle] = time.time()
        if not was_present:
            self.announce_join(room, handle)

    def _announced_in(self, room: str) -> set[str]:
        """The handles already announced in ``room``, read from its folder once."""
        known = self._announced.get(room)
        if known is None:
            known = _load_announced(room)
            self._announced[room] = known
        return known

    def announce_join(self, room: str, handle: str, intent: str = "") -> bool:
        """Emit a coordination_join notice on the first not-present → present transition.

        Once per member per room: returns False (and does nothing) if the handle
        has been announced here before, across lapsed leases, reconnects and
        restarts. Only :meth:`remove` forgets it, so a member removed and added
        again is announced again. Called from every join path so the channel feed
        shows arrivals consistently, whether the agent joined via an HTTP
        session or an ``await`` lease.
        """
        announced = self._announced_in(room)
        if handle in announced:
            return False
        announced.add(handle)
        _save_announced(room, announced)
        content = json.dumps({"handle": handle, "intent": intent})
        try:
            from app.services import in_memory_store

            in_memory_store.add_message(
                room,
                in_memory_store.StoredMessage(
                    room_name=room,
                    sender_handle=message_format.SYSTEM_ACTOR_ID,
                    message_type="coordination_join",
                    content=content,
                ),
            )
        except Exception:
            logger.debug("join notice persist failed for %s in room %s", handle, room)
        try:
            from app.bus import bus, room_channel

            bus.publish(
                room_channel(room),
                {
                    "room_name": room,
                    "sender_handle": message_format.SYSTEM_ACTOR_ID,
                    "message_type": "coordination_join",
                    "content": content,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            logger.debug("join notice bus publish failed for %s in room %s", handle, room)
        return True

    def _summon_adapter(self, room: str) -> SummonHook:
        """Bind ``room`` onto the room-aware ``on_summon`` hook.

        The persister calls its ``SummonHook`` with only ``(handle, envelope)``;
        the engine wired to :attr:`on_summon` needs the room too. The hook is
        read at call time, so a room opened before the engines were wired still
        reaches them.
        """

        def adapter(
            handle: str,
            envelope: MyceliumMessage,
            co_summons: list[str],
            message_text: str = "",
            _room: str = room,
        ) -> None:
            hook = self.on_summon
            if hook is None:
                logger.info("@%s summoned in %s, with no engines wired", handle, _room)
                return
            hook(_room, handle, envelope, co_summons, message_text)

        return adapter

    def _asked_adapter(self, room: str) -> AskedHook:
        """What the persister calls for each handle a message asks: ring its
        doorbell (:meth:`ring_asked`), and hand a turn to :attr:`on_turn`, read
        at call time so a hook wired after the room started still hears it."""

        def adapter(
            handle: str,
            reason: str,
            envelope: MyceliumMessage,
            message_text: str = "",
            _room: str = room,
        ) -> None:
            message = envelope.header.message
            self.ring_asked(
                _room,
                handle,
                reason,
                sender=envelope_sender(envelope),
                episode=message.episode if message else None,
                message=envelope_message_id(envelope),
            )
            hook = self.on_turn
            if reason == "turn" and hook is not None:
                hook(_room, handle, envelope, message_text)

        return adapter

    def _recorded_adapter(self, room: str) -> Callable[[TranscriptRecord], None] | None:
        """Bind ``room`` onto the room-aware ``on_recorded`` hook. Read at call
        time, so a hook wired after the room's persister started still fires.
        The subscriptions' doorbell rings here first (:meth:`ring_subscribed`)."""

        def adapter(record: TranscriptRecord, _room: str = room) -> None:
            try:
                self.ring_subscribed(_room, record)
            except Exception:
                logger.exception("subscriptions: ringing failed for %s", record.message_id)
            hook = self.on_recorded
            if hook is not None:
                hook(_room, record)

        return adapter

    # -- human-in-the-room --

    async def publish_human(
        self,
        room: str,
        *,
        sender: str,
        text: str,
        subkind: str | None = None,
        parents: list[str] | None = None,
        episode: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> HumanPublishResult:
        """Record a person's message in the room, as their proxy.

        The person runs no agent: the backend builds an ``exchange`` message on
        their behalf and maps ``@agent-x`` tokens to message recipients, which
        is who it wakes.

        ``subkind``/``parents`` carry an ``amend`` revising an earlier message,
        the same publish in every other respect, since a revision is a message
        the room hears like any other, mentions included. A reaction rides the
        same way, with ``data`` carrying its ``reaction`` beside the text.

        ``episode`` names the **thread** the message lands in; without one it
        lands in the room itself. A thread is a tag over this same channel, so a
        threaded message is recorded exactly like any other; what changes is
        only that it does not clutter the room. The :meth:`raise_ping` that
        surfaces it there is the *caller's*: this publish is one of several
        ways a message reaches a thread, and a ping raised from inside it would
        be silently skipped by every other one.
        """
        managed = self._channels.get(room) or self.open(room)

        mentioned = parse_mentions(text)
        # ``@here`` and ``@all`` reach who they reach now, kept on the message so
        # every later read of who it asked gives the same answer.
        extra, by_group = groups.on_message(room, text=text, episode=episode, sender=sender)
        if data:
            extra = {**data, **extra}
        # Every mention is a message recipient (the semantic "to"); everyone
        # else in the room is an observer.
        envelope = message_format.build_envelope(
            kind=Kind.exchange,
            subkind=subkind,
            episode=episode or message_format.live_episode_urn(room),
            parents=parents,
            sender=sender,
            sender_role="human",
            recipients=mentioned + [h for h in by_group if h not in mentioned],
            topic=message_format.topic_urn(room),
            payload_type="message",
        )
        content = serialize_content(envelope, extra=extra)
        message_id = envelope.header.message.id if envelope.header.message else None
        # Transcript-only here (``list_write=False``): the POST route owns the
        # ``in_memory_store`` row (its id/ledger), stamped with this envelope's id so
        # a cold read dedups the two.
        managed.persister.record(envelope, content, list_write=False)

        # A mention of anyone who is neither present nor a registered agent of
        # the room (another person, a typo) is addressed but reaches no one.
        present = set(self.members(room))
        unrecognized = [
            h
            for h in mentioned
            if h not in present and h != BACKEND_AGENT and not _is_own_registered_agent(room, h)
        ]

        recipients = [h for h in mentioned if h != BACKEND_AGENT]
        return HumanPublishResult(
            mentioned=mentioned,
            recipients=recipients,
            unrecognized=unrecognized,
            message_id=message_id,
        )

    async def raise_ping(
        self,
        room: str,
        *,
        episode: str | None,
        sender: str,
        message_id: str | None,
    ) -> str | None:
        """Raise a thread's activity into ``live`` as a **ping**, and nothing more.

        The room stays legible because a thread absorbs its own noise: what
        surfaces is that a task moved, not what was said in it. So the ping
        carries no text — only the thread it is about, who wrote, and the id of
        the message, which is enough for a reader to open the thread and no use
        to anyone trying to read it without.

        Two properties it must hold, both structural rather than a convention a
        later caller has to remember:

        *It wakes nobody.* The ping is addressed to no one and rides a ``ping``
        payload, which asks nobody (:func:`app.services.asks.asks`) the same
        way presence doesn't — so a resident agent's ``await`` consumes
        it silently instead of spending a turn on it.

        Returns the ping's message id, or ``None`` when there is nothing to
        announce — a message in the room itself, which *is* the room.
        """
        if episode is None or message_format.is_live_episode(room, episode):
            return None
        ping = message_format.build_envelope(
            kind=Kind.exchange,
            episode=message_format.live_episode_urn(room),
            sender=message_format.SYSTEM_ACTOR_ID,
            sender_role=message_format.SYSTEM_ACTOR_ROLE,
            topic=message_format.topic_urn(room),
            payload_type=message_format.PING_PAYLOAD_TYPE,
            payload_data={
                "episode": episode,
                "sender": sender,
                **({"message": message_id} if message_id else {}),
            },
        )
        (self._channels.get(room) or self.open(room)).persister.record(
            ping, serialize_content(ping), list_write=False
        )
        return ping.header.message.id if ping.header.message else None

    async def raise_notice(
        self,
        room: str,
        *,
        subkind: str,
        key: str,
        title: str | None = None,
        episode: str | None = None,
        by: str | None = None,
        **extra: str | None,
    ) -> None:
        """Raise a **notice** into ``live``: the room's timeline of board events.

        The sibling of :meth:`raise_ping`, and it holds the same two structural
        property: it wakes nobody (a ``notice`` payload, which asks nobody:
        :func:`app.services.asks.asks`), so a task filed, claimed, handed back or
        resolved reads in the channel in sequence with the chat without
        spending an agent's turn.

        Where a ping says a thread moved, a notice says the board did: it names
        the task (``key``/``title``), the thread to open (``episode``), and who
        moved it (``by``). ``subkind`` is one of :data:`app.services.message_format.NOTICE_SUBKINDS`.
        """
        data: dict[str, str] = {"subkind": subkind, "key": key}
        for name, value in (("title", title), ("episode", episode), ("by", by), *extra.items()):
            if value:
                data[name] = value
        notice = message_format.build_envelope(
            kind=Kind.exchange,
            episode=message_format.live_episode_urn(room),
            sender=message_format.SYSTEM_ACTOR_ID,
            sender_role=message_format.SYSTEM_ACTOR_ROLE,
            topic=message_format.topic_urn(room),
            payload_type=message_format.NOTICE_PAYLOAD_TYPE,
            payload_data=data,
        )
        (self._channels.get(room) or self.open(room)).persister.record(
            notice, serialize_content(notice), list_write=False
        )
        if self.on_notice is not None:
            try:
                self.on_notice(room, dict(data))
            except Exception:
                logger.exception("notice hook failed for %s in %s", subkind, room)

    async def remove(self, room: str, agent: str) -> bool:
        """Take ``agent`` out of the room: its lease lapses, its arrival is
        forgotten, and a negotiation it was a party to ends. True when it was
        present or announced."""
        managed = self._channels.get(room)
        if managed is None:
            return False
        leases = self._leases.get(room, {})
        was_present = leases.pop(agent, None) is not None
        self._last_seen.get(room, {}).pop(agent, None)
        # Removed from the room: if they're added again, that's a new arrival.
        announced = self._announced_in(room)
        was_announced = agent in announced
        if was_announced:
            announced.discard(agent)
            _save_announced(room, announced)
        await self._abort_if_party_left(managed, agent)
        return was_present or was_announced

    def rename_member(self, room: str, old: str, new: str) -> None:
        """Carry what the room holds for ``old`` over to ``new``.

        Its presence (lease, last seen, herdr status), its pending doorbell, the
        floors it was given, whether it was announced, and its read positions, so
        the renamed agent is the same member under its new name: present if it
        was, woken by a mention of ``new`` before its machine's next sync pass,
        and not handed the room again from the start.
        """
        for times in (self._leases.get(room), self._last_seen.get(room)):
            if times and old in times:
                times[new] = times.pop(old)
        for entries in self._herdr.get(room, {}).values():
            if old in entries:
                entries[new] = entries.pop(old)
        for wake in self._herdr_wakes.get(room, []):
            if wake.get("handle") == old:
                wake["handle"] = new
        announced = self._announced_in(room)
        if old in announced:
            announced.discard(old)
            announced.add(new)
            _save_announced(room, announced)
        managed = self.get(room)
        if managed is None:
            return
        for episode, floor in list(managed.floors.items()):
            holder = new if floor.holder == old else floor.holder
            speakers = frozenset(new if s == old else s for s in floor.speakers)
            if (holder, speakers) != (floor.holder, floor.speakers):
                managed.floors[episode] = Floor(episode, holder, speakers, floor.since)
        managed.persister.rename_handle(old, new)

    def open_episode(
        self,
        room: str,
        episode: str,
        *,
        negotiation: bool = True,
        parties: Iterable[str] = (),
    ) -> bool:
        """Open an episode; a negotiation freezes on its ``parties``.

        The parties are who the negotiation brokers between (the members a
        summon named, or a task's members), never everyone present: freezing
        the room's whole presence is how a busy room's comings and goings
        aborted runs and pulled in members nobody named. Only one of the
        parties being removed from the room ends the run
        (:meth:`_abort_if_party_left`). ``negotiation=False`` opens a container
        — a task's thread — which nothing ends, because the task outlives what
        happens inside it.
        """
        managed = self.get(room)
        if managed is None:
            return False
        frozen = {h for h in (norm_handle(p) for p in parties) if h}
        managed.lifecycle.open(episode, frozen, negotiation=negotiation)
        return True

    # -- the floor --

    def hold_floor(
        self, room: str, episode: str, *, holder: str, speakers: Iterable[str] = ()
    ) -> Floor | None:
        """Give ``speakers`` the floor in ``episode``, held by ``holder``.

        Replaces whatever floor the thread held, so a runner moving from one
        step to the next calls this once per step. ``None`` when the room has
        no folder, or when ``episode`` is the room itself: the room never holds
        a floor, so a protocol cannot close the room around itself.
        """
        managed = self.get(room)
        if managed is None or message_format.is_live_episode(room, episode):
            return None
        previous = managed.floors.get(episode)
        floor = Floor(
            episode=episode,
            holder=norm_handle(holder) or holder,
            speakers=frozenset(h for h in (norm_handle(s) for s in speakers) if h),
            since=datetime.now(UTC),
        )
        if previous is not None and previous == floor:
            # The same turn re-held: it has been waiting since it was first given.
            floor = previous
        managed.floors[episode] = floor
        if previous != floor:
            # Whose turn it is changed: one line in the room's timeline, and the
            # roster re-reads. Nothing when a step re-holds the same floor.
            self._notice_in_background(
                room,
                subkind="floor",
                **self._floor_names(room, episode),
                by=floor.holder,
                speakers=",".join(sorted(floor.speakers)),
            )
        return floor

    @staticmethod
    def _floor_names(room: str, episode: str) -> dict[str, str | None]:
        """How a floor notice names its thread: by the task it belongs to.

        A task and its thread are one object, so a line about the thread says
        the task's key and title; only a thread no row carries falls back to
        the id. The lookup is the store's, done lazily so this module does not
        import the task model at load.
        """
        from app.services.tasks import row_of_episode

        row = row_of_episode(room, episode)
        if row is None:
            return {"key": episode.rsplit(":", 1)[-1], "episode": episode, "title": None}
        return {"key": row[0], "episode": episode, "title": row[1]}

    def release_floor(self, room: str, episode: str) -> bool:
        """Open ``episode`` back up; True when a floor was actually held."""
        managed = self._channels.get(room)
        if managed is None:
            return False
        floor = managed.floors.pop(episode, None)
        if floor is None:
            return False
        self._notice_in_background(
            room,
            subkind="floor",
            **self._floor_names(room, episode),
            by=floor.holder,
            released="1",
        )
        return True

    def floors_of(self, room: str) -> list[Floor]:
        """Every floor held in ``room`` right now, in thread order."""
        managed = self._channels.get(room)
        if managed is None:
            return []
        return [managed.floors[key] for key in sorted(managed.floors)]

    def _notice_in_background(self, room: str, **notice: str | None) -> None:
        """Raise a notice from a sync caller, on the running loop if there is one."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.raise_notice(room, **notice))  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def floor(self, room: str, episode: str | None) -> Floor | None:
        """The floor ``episode`` holds, or ``None`` when anyone may write."""
        managed = self._channels.get(room)
        if managed is None or episode is None:
            return None
        return managed.floors.get(episode)

    async def close_episode(self, room: str) -> bool:
        """Close the room's active episode normally."""
        managed = self._channels.get(room)
        if managed is None:
            return False
        managed.lifecycle.close()
        return True

    async def _abort_if_party_left(self, managed: ManagedRoomChannel, agent: str) -> None:
        """End the running negotiation when ``agent``, one of its parties, left the room.

        Only the ``remove`` path calls this: presence starting or lapsing is not
        leaving (see :class:`EpisodeLifecycle`). The abort is recorded here,
        as one plain line, never a bare protocol record.
        """
        handle = norm_handle(agent) or agent
        if not managed.lifecycle.on_member_removed(handle):
            return
        episode = managed.lifecycle.episode
        managed.lifecycle.close()
        if not episode:
            return
        logger.info("@%s left %s, ending the negotiation in %s", handle, managed.room, episode)
        envelope = build_episode_abort_envelope(
            episode,
            recipients=sorted(managed.lifecycle.members),
            topic=message_format.topic_urn(managed.room),
            reason="party_left",
        )
        line = f"Negotiation stopped: {handle} left the room."
        managed.persister.record(envelope, serialize_content(envelope, extra={"content": line}))

    async def close(self, room: str) -> None:
        """Forget the room's channel (the room was deleted)."""
        if self._channels.pop(room, None) is not None:
            logger.info("Closed the channel for room %s", room)

    async def close_all(self) -> None:
        """Forget every channel and cancel background work (shutdown)."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._channels.clear()


# Process-wide registry: the backend is a single always-on process, so one
# channel per room lives here.
manager = RoomChannelManager()
