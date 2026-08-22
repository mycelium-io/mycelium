# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The summonguard — an engine that decides which ``@``-mentions are summons.

A room treats every ``@handle`` as a wake: the persister fires the summon seam
and the handle's next ``await`` returns that message as its turn. That is right
for ``@alice can you cost this out?`` and wrong for ``we shipped it, credit to
@alice`` — the second is *provenance*, and waking a resident agent for it burns
a turn (and, for an engine, can restart a negotiation that already converged).

The summonguard is the engine kind that tells the two apart. Registering it in a
room installs a :data:`~app.services.engine_events.SUMMON_FILTER` hook (see
:mod:`app.services.engine_events`); the room's summon path then asks that hook
before waking anyone. No guard registered → no hook → the room behaves exactly
as it did.

Three properties hold it together:

* **Fail open, always.** Every failure mode — Pi missing, timed out, empty,
  unparseable, a handle the classifier forgot — resolves to ``wake``. A guard
  outage costs a spurious wake, never a silenced summon. The kill switch
  (``SUMMONGUARD_DISABLE``) resolves the same way.
* **A regex may confirm a wake, never suppress one.** The cheap pre-pass
  (:func:`_leading_mention_is_wake`) short-circuits the overwhelmingly common
  summon shape — the mention opening the message — so the hot path costs no
  cognition. Suppression is only ever a model's judgement, never a pattern's.
* **One classification per message.** The persister classifies at ingest, for
  every mentioned handle at once, and the verdict is stored by message id. The
  ``await`` long-poll reads that verdict rather than classifying again, so the
  two paths can never disagree, and the poll simply absorbs the latency it takes
  to produce.

Like the synthesizer, cognition is one throwaway ``pi`` turn off the event loop
— no session, no memory between messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services import l9
from app.services.engine_events import SUMMON_FILTER, RoomEvent, RoomEventContext, lifecycle
from app.services.l9_slim import serialize_content

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)

#: The engine kind this module owns.
ENGINE_KIND = "summonguard"

#: The two verdicts. ``wake`` serves the message as the handle's turn (today's
#: behaviour); ``mention`` records it and lets the handle sleep.
WAKE = "wake"
MENTION = "mention"

#: Handles that are room infrastructure rather than wakeable participants.
_NEVER_CLASSIFIED = frozenset({"system", "backend", "everyone", "here", "room", "all"})

#: How many verdicts per room the introspection surface keeps. Small on purpose:
#: this is a "why didn't @alice wake?" window, not an audit log — the transcript
#: is the durable record.
_VERDICT_HISTORY = 100

_LEADING_MENTION_RE = re.compile(r"^\s*(?:@[A-Za-z0-9][\w-]*[\s,:]*)+")
_MENTION_RE = re.compile(r"(?:^|(?<=[\s(<]))@([A-Za-z0-9][\w-]*)")


# ── Verdict types (pure) ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class SummonContext:
    """What the filter is asked to judge: one message, its mentioned handles."""

    room: str
    message_id: str
    sender: str
    text: str
    handles: tuple[str, ...]


@dataclass
class SummonVerdict:
    """One message's decisions, plus how they were reached."""

    room: str
    message_id: str
    sender: str
    text: str
    #: handle -> ``wake`` | ``mention``
    decisions: dict[str, str]
    #: handle -> one-line justification (empty for short-circuited wakes)
    reasons: dict[str, str] = field(default_factory=dict)
    #: ``pi`` | ``leading-mention`` | ``fail-open`` | ``disabled`` | ``mixed``
    source: str = "pi"
    decided_at: str = ""

    def wakes(self, handle: str) -> bool:
        """True unless this verdict explicitly classified ``handle`` as provenance."""
        return self.decisions.get(_norm(handle), WAKE) != MENTION

    def as_dict(self) -> dict[str, Any]:
        return {
            "room": self.room,
            "message_id": self.message_id,
            "sender": self.sender,
            "text": self.text,
            "decisions": dict(self.decisions),
            "reasons": dict(self.reasons),
            "source": self.source,
            "decided_at": self.decided_at,
        }


def _norm(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _leading_mention_is_wake(text: str, handle: str) -> bool:
    """True when ``@handle`` opens the message — the plain summon shape.

    ``@alice thoughts?`` and ``@alice @bob let's settle this`` address their
    handles; a mention anywhere further in is where provenance lives. Confirming
    a wake here is safe in a way suppressing one would not be, so this is the
    only decision made without cognition.
    """
    match = _LEADING_MENTION_RE.match(text or "")
    if match is None:
        return False
    lead = {_norm(h) for h in _MENTION_RE.findall(match.group(0))}
    return _norm(handle) in lead


def parse_decisions(raw: str, handles: tuple[str, ...]) -> tuple[dict[str, str], dict[str, str]]:
    """Read the classifier's JSON into ``(decisions, reasons)``.

    Tolerant of a wrapping code fence or prose either side of the object, since
    that is what models actually emit. Anything unreadable — a missing handle, a
    verdict that is neither value — is simply left out, and the caller fills the
    gap with ``wake``: an unparseable classification must never suppress.
    """
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}, {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}

    wanted = {_norm(h) for h in handles}
    decisions: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for key, value in data.items():
        handle = _norm(str(key))
        if handle not in wanted:
            continue
        if isinstance(value, str):
            verdict, reason = value, ""
        elif isinstance(value, dict):
            verdict = str(value.get("decision") or value.get("verdict") or "")
            reason = str(value.get("reason") or "")
        else:
            continue
        verdict = verdict.strip().lower()
        if verdict not in (WAKE, MENTION):
            continue
        decisions[handle] = verdict
        if reason:
            reasons[handle] = reason.strip()
    return decisions, reasons


def build_prompt(ctx: SummonContext) -> str:
    """The classifier prompt. Pure — unit-testable without a Pi binary."""
    roster = "\n".join(f"- @{h}" for h in ctx.handles)
    return (
        "You are the summon guard for a Mycelium coordination room. A message was "
        "posted that mentions one or more agents. For each mentioned handle, decide "
        "whether the mention is a SUMMON (the message asks that agent to do or say "
        "something now — it should be woken and take a turn) or a REFERENCE (the "
        "message merely names the agent — attribution, credit, provenance, "
        "narration, or a note addressed to someone else — and waking it would waste "
        "a turn).\n\n"
        "Judge each handle separately: one message can summon one agent while only "
        "referring to another.\n\n"
        "When you are genuinely unsure, answer 'wake'. A missed summon stalls the "
        "room; a spurious wake only costs a turn.\n\n"
        f"Room: {ctx.room}\n"
        f'Message from @{ctx.sender}:\n"""\n{ctx.text.strip()}\n"""\n\n'
        f"Mentioned handles:\n{roster}\n\n"
        'Reply with ONLY a JSON object mapping each handle (no "@") to '
        '{"decision": "wake"|"mention", "reason": "<max 12 words>"}. '
        "No prose, no code fence."
    )


def _pi_complete(prompt: str, timeout_s: float) -> str:
    """One blocking Pi turn producing the raw classification JSON.

    A throwaway ``--session`` file keeps it a true one-shot: the guard judges
    each message on its own text, with no memory to drift on. Isolated so tests
    patch it without a live Pi.
    """
    from app.services.pi_brain import PiBrain

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    brain = PiBrain(
        session_path=session_dir / f"summonguard-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=timeout_s,
        openshell=settings.ALIGNER_PI_OPENSHELL,
    )
    return brain(prompt)


# ── Verdict store ────────────────────────────────────────────────────────────


class VerdictStore:
    """Per-room verdicts by message id, with waiters for the classification.

    The persister classifies on ingest; ``await`` needs the answer for the same
    message a moment later. Rather than have the poll classify again (and risk
    the two paths disagreeing), it waits here on the event this store sets.
    """

    def __init__(self, history: int = _VERDICT_HISTORY) -> None:
        self._history = history
        self._by_room: dict[str, OrderedDict[str, SummonVerdict]] = {}
        self._waiters: dict[tuple[str, str], asyncio.Event] = {}

    def _event(self, room: str, message_id: str) -> asyncio.Event:
        return self._waiters.setdefault((room, message_id), asyncio.Event())

    def begin(self, room: str, message_id: str) -> None:
        """Mark a classification in flight so a waiter blocks instead of failing open."""
        self._event(room, message_id)

    def put(self, verdict: SummonVerdict) -> None:
        room = self._by_room.setdefault(verdict.room, OrderedDict())
        room[verdict.message_id] = verdict
        while len(room) > self._history:
            room.popitem(last=False)
        self._event(verdict.room, verdict.message_id).set()

    def get(self, room: str, message_id: str) -> SummonVerdict | None:
        return self._by_room.get(room, {}).get(message_id)

    def pending(self, room: str, message_id: str) -> bool:
        """True when a classification was started for this message and hasn't landed."""
        event = self._waiters.get((room, message_id))
        return event is not None and not event.is_set()

    async def wait(self, room: str, message_id: str, timeout_s: float) -> SummonVerdict | None:
        """The verdict for a message, waiting up to ``timeout_s`` for one in flight."""
        existing = self.get(room, message_id)
        if existing is not None:
            return existing
        if not self.pending(room, message_id):
            return None
        try:
            await asyncio.wait_for(self._event(room, message_id).wait(), timeout=timeout_s)
        except TimeoutError:
            return None
        return self.get(room, message_id)

    def recent(self, room: str, limit: int = 20) -> list[SummonVerdict]:
        """Most recent verdicts for ``room``, newest first."""
        return list(reversed(list(self._by_room.get(room, {}).values())))[:limit]

    def clear(self) -> None:
        self._by_room.clear()
        self._waiters.clear()


#: Process-wide store — the persister writes, ``await`` and the route read.
verdicts = VerdictStore()


# ── The engine ───────────────────────────────────────────────────────────────


class SummonGuardEngine:
    """Installs a summon filter into every room that registers it.

    Unlike the aligner and the synthesizer — engines that *act* when summoned —
    this one's work happens on registration: it subscribes to the room lifecycle
    and keeps each room's :data:`SUMMON_FILTER` hook in sync with that room's
    manifests. Summoning it directly just asks it what it has been deciding.
    """

    def __init__(
        self,
        manager: RoomChannelManager,
        *,
        timeout_s: float | None = None,
    ) -> None:
        self._manager = manager
        self._timeout_s = timeout_s if timeout_s is not None else settings.SUMMONGUARD_PI_TIMEOUT_S
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- lifecycle wiring --

    def wire(self) -> None:
        """Subscribe to the lifecycle events that install/remove the hook."""
        for event in (
            RoomEvent.ENGINE_REGISTERED,
            RoomEvent.ENGINE_REMOVED,
            RoomEvent.ROOM_PROVISIONED,
        ):
            lifecycle.subscribe(event, self._on_lifecycle)

    def _on_lifecycle(self, ctx: RoomEventContext) -> None:
        self.sync_room(ctx.room)

    def sync_room(self, room: str) -> list[str]:
        """Reconcile ``room``'s summon filter against its registered manifests.

        Reads the room's engine manifests rather than trusting the event
        payload, so it is idempotent and self-healing: a guard registered while
        the backend was down installs on the room's next provision, and one
        deleted from the room drops out on the next lifecycle event.
        """
        guards = self._registered_guards(room)
        for owner in guards:
            lifecycle.install(room, SUMMON_FILTER, owner, self.classify)
        for owner in lifecycle.owners(room, SUMMON_FILTER):
            if owner not in guards:
                lifecycle.uninstall(room, SUMMON_FILTER, owner)
        return guards

    @staticmethod
    def _registered_guards(room: str) -> list[str]:
        """Handles in ``room`` whose manifest is ``adapter: engine, kind: summonguard``."""
        from app.services.agent_registry import room_agents

        try:
            agents = room_agents(room)
        except Exception:
            logger.exception("summonguard: could not read manifests for room %s", room)
            return []
        return [a.handle for a in agents if a.adapter == "engine" and a.kind == ENGINE_KIND]

    # -- the filter itself (the installed hook) --

    async def classify(self, ctx: SummonContext) -> dict[str, str]:
        """Decide each mentioned handle in one message; publish the verdict.

        Returns the ``{handle: wake|mention}`` map, and stores the full verdict
        (with reasons) so ``await`` and the introspection route read the same
        decision rather than re-deriving it.
        """
        candidates = tuple(
            h for h in dict.fromkeys(_norm(h) for h in ctx.handles) if h not in _NEVER_CLASSIFIED
        )
        decisions: dict[str, str] = {}
        reasons: dict[str, str] = {}
        source = "pi"

        # The kill switch stops the classification, not the verdict: every
        # candidate falls through to the wake default below.
        disabled = settings.SUMMONGUARD_DISABLE
        if disabled:
            source = "disabled"

        # Cheap pre-pass: a mention that opens the message is a summon. Only
        # what it leaves undecided is worth a cognition turn.
        undecided = []
        for handle in () if disabled else candidates:
            if _leading_mention_is_wake(ctx.text, handle):
                decisions[handle] = WAKE
            else:
                undecided.append(handle)
        if decisions and not undecided:
            source = "leading-mention"

        if undecided:
            judged, judged_reasons, ok = await self._judge(ctx, tuple(undecided))
            decisions.update(judged)
            reasons.update(judged_reasons)
            if not ok:
                source = "fail-open"
            elif len(decisions) > len(judged):
                source = "mixed"

        # Anything still unanswered fails open — the classifier skipping a handle
        # must not be the reason it stays asleep.
        for handle in candidates:
            decisions.setdefault(handle, WAKE)

        verdict = SummonVerdict(
            room=ctx.room,
            message_id=ctx.message_id,
            sender=ctx.sender,
            text=ctx.text,
            decisions=decisions,
            reasons=reasons,
            source=source,
            decided_at=_now(),
        )
        verdicts.put(verdict)
        suppressed = [h for h, d in decisions.items() if d == MENTION]
        if suppressed:
            logger.info(
                "summonguard: room %s message %s — %s mentioned for provenance, not woken",
                ctx.room,
                ctx.message_id,
                ", ".join(f"@{h}" for h in suppressed),
            )
        return decisions

    async def _judge(
        self, ctx: SummonContext, handles: tuple[str, ...]
    ) -> tuple[dict[str, str], dict[str, str], bool]:
        """One Pi turn over ``handles``; ``(decisions, reasons, succeeded)``."""
        prompt = build_prompt(replace(ctx, handles=handles))
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_pi_complete, prompt, self._timeout_s),
                timeout=self._timeout_s + 5.0,
            )
        except Exception as exc:
            logger.warning(
                "summonguard: classification failed on room %s (%s) — failing open to wake",
                ctx.room,
                exc,
            )
            return {}, {}, False
        decisions, reasons = parse_decisions(raw or "", handles)
        if not decisions:
            logger.warning(
                "summonguard: unreadable classification on room %s — failing open to wake", ctx.room
            )
            return {}, {}, False
        return decisions, reasons, True

    # -- the summon seam (the guard, summoned itself) --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: L9,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        """Report what the guard has been deciding when it is summoned by name.

        The guard has no work to *do* on summon — its work is the filter it
        already installed — so a summon is answered with its recent decisions,
        which is what someone asking it is actually after.
        """
        from app.services.aligner import _registered_engine_kind
        from app.services.persister import envelope_sender

        if _registered_engine_kind(room, handle) != ENGINE_KIND:
            return
        sender = envelope_sender(envelope)
        if sender is not None and _norm(sender) == _norm(handle):
            return
        task = asyncio.create_task(self._report(room, handle))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _report(self, room: str, me: str) -> None:
        managed = self._manager.get(room)
        if managed is None:
            return
        recent = verdicts.recent(room, limit=5)
        if not recent:
            body = "Guarding this room's summons. Nothing classified yet."
        else:
            lines = ["Recent summon decisions (newest first):"]
            for verdict in recent:
                for h, d in verdict.decisions.items():
                    why = verdict.reasons.get(h, "")
                    lines.append(f"- @{h}: {d}" + (f" — {why}" if why else ""))
            body = "\n".join(lines)
        await self._say(managed, room, me, body)

    async def _say(self, managed: ManagedRoomChannel, room: str, sender: str, text: str) -> None:
        env = l9.build_envelope(
            kind=l9.Kind.exchange,
            episode=l9.episode_urn(room, "live"),
            sender=sender,
            topic=l9.topic_urn(room),
            payload_type="message",
        )
        content = serialize_content(env, extra={"content": text})
        try:
            await managed.channel.send(env, extra={"content": text})
        except Exception:
            logger.warning("summonguard failed to broadcast on room %s", room)
        if managed.persister is not None:
            managed.persister.ingest_local(env, content)


# ── The two consumer-facing helpers ──────────────────────────────────────────


def guarded(room: str) -> bool:
    """True when some engine installed a summon filter in ``room``."""
    return bool(lifecycle.hooks(room, SUMMON_FILTER))


async def decide(ctx: SummonContext) -> dict[str, str]:
    """Run ``ctx`` through every summon filter installed in its room.

    With no filter installed every handle wakes — today's behaviour. With
    several, a handle is suppressed only when **all** of them call it provenance:
    the guards are advisory, and the fail-open bias holds across them too.
    """
    filters = lifecycle.hooks(ctx.room, SUMMON_FILTER)
    if not filters:
        return {_norm(h): WAKE for h in ctx.handles}
    verdicts.begin(ctx.room, ctx.message_id)
    merged: dict[str, str] = {}
    for fn in filters:
        try:
            result = await fn(ctx)
        except Exception:
            logger.exception("summon filter failed on room %s — failing open", ctx.room)
            return {_norm(h): WAKE for h in ctx.handles}
        for handle, decision in (result or {}).items():
            key = _norm(handle)
            if merged.get(key, MENTION) == MENTION and decision == MENTION:
                merged[key] = MENTION
            else:
                merged[key] = WAKE
    for handle in ctx.handles:
        merged.setdefault(_norm(handle), WAKE)
    return merged


async def wakes(room: str, message_id: str, handle: str) -> bool:
    """Whether ``handle`` should be woken by ``message_id`` (the ``await`` gate).

    Waits out an in-flight classification — the long-poll has the time, and the
    alternative is delivering a turn the guard was about to suppress. An
    unguarded room, an unclassified message, or a classification that overruns
    the wait all answer ``True``.
    """
    if not guarded(room):
        return True
    verdict = await verdicts.wait(room, message_id, settings.SUMMONGUARD_WAKE_TIMEOUT_S)
    if verdict is None:
        return True
    return verdict.wakes(handle)
