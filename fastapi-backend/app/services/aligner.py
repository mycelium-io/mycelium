# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The SIEP aligner — the first cognition engine.

Three things are split apart here that would otherwise be bundled as "the CE":

1. **Room infrastructure** — membership + durable transcript. That is the
   always-on backend (``room_channels`` + ``persister``); cheap, always
   listening. *Not* cognition.
2. **Protocol machinery** — the deterministic MPC/GAR/SCR math over the
   transcript. That already lives in :mod:`app.services.l9_episode`; this engine
   *calls* it and never re-derives it (a second copy would drift from the
   ``log/episodes/*`` records).
3. **Cognitive judgment** — "is this converged, and what is the agreement?" That
   is *this* module, and only this module. It is a **family** (one engine per L9
   sub-protocol); the MVP ships **SIEP** — convergence — only.

**Cost is a first-class constraint.** The engine is **dormant by default (zero
idle cost).** Nothing here runs until an explicit ``@``-summon of the reserved
aligner handle arrives through the persister's summon seam — no polling, no held
LLM connection. The cheap backend does the listening; the engine only wakes when
called.

**One path, once summoned: mediate.** The engine opens an episode (freezing
membership), discovers the negotiable issues from the participants' opening prose,
and drives a live **NEGMAS SAO** to termination — ``@``-addressing one participant
per turn over the room channel, interpreting the real reply, and stopping the
*instant* the mechanism reaches unanimity (the anti-theater property). It hands
the agreed ``issue = value`` map to the ``commit:converged`` seam ``task_sync``
consumes (a failed run commits ``rejected``). Deterministic scoring (MPC/GAR/SCR)
still rides along via :mod:`l9_episode`, computed over the mediator's readings.

**Runtime note.** This runs **in-process in the backend** — the ``commit``
envelope is emitted onto the channel the backend moderates, and the mediator's own
LLM session is a Pi agent (:mod:`app.services.pi_session`, always Pi). Participants answer
over the channel however they run (a daemon cold-spawn, or a server-held CLI
``await``/``respond`` caller) — the engine only ``@``-addresses them; it never
spawns a judge of its own.
"""

from __future__ import annotations

import asyncio
import copy
import functools
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services import activity, l9, l9_episode
from app.services.agent_registry import norm_handle
from app.services.room_channels import BACKEND_AGENT

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.services.l9_episode import NegotiationState
    from app.services.l9_models import L9
    from app.services.persister import RoomPersister, TranscriptRecord
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)


# Handles that are never a participant position: the engine itself, the backend
# moderator, and the system actor the backend signs its own envelopes with.
_NON_PARTICIPANTS = frozenset({BACKEND_AGENT, l9.SYSTEM_ACTOR_ID})

# The mediator addresses exactly ONE agent per turn via the L9 ``recipients``
# field. Its prompt *text*, though, embeds the broker's summary which names the
# other participants — and the connector's ``should_wake`` also wakes on a raw
# ``@handle`` token in the human-facing text. Left as-is, every turn would
# spuriously wake *every* named agent, doubling cold-spawns and serializing the
# connectors until the addressed agent's real reply misses the round window (the
# turn then falls back to a reject). Neutralizing the ``@`` means only the
# L9-addressed agent wakes; the names stay readable.
_AT_MENTION = re.compile(r"@(?=\w)")

# Round number stamped on the pre-negotiation clarifying tick. SAO steps are
# NEGMAS's own, counted from 1, so round 0 marks the turn that ran before the
# mechanism existed.
_CLARIFY_ROUND = 0


def _registered_engine_kind(room: str, handle: str) -> str | None:
    """The CE kind if ``handle`` is a registered ``engine`` agent in ``room``.

    The agent manifest is stored as YAML in the body of ``agents/<handle>`` (the
    CLI's ``mycelium engine create`` writes ``adapter: engine`` + ``kind:``).
    Returns the ``kind`` for an engine manifest, else ``None`` — so summoning a
    normal teammate, or a handle with a missing/broken manifest, never fires the
    aligner. Cheap: summons are rare and this is one small file read.
    """
    import yaml

    from app.services.filesystem import get_room_dir, read_memory_file

    result = read_memory_file(get_room_dir(room), f"agents/{handle}")
    if result is None:
        return None
    _meta, body = result
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        return None
    if isinstance(data, dict) and data.get("adapter") == "engine":
        kind = data.get("kind")
        return kind if isinstance(kind, str) else None
    return None


def _norm(handle: str) -> str:
    return norm_handle(handle) or ""


def _new_episode_id() -> str:
    """Generate a unique episode id (used in URN, filename, wire)."""
    return uuid.uuid4().hex[:8]


def _payload(content: dict[str, Any]) -> dict[str, Any]:
    env = content.get("l9")
    if not isinstance(env, dict):
        return {}
    payload = env.get("payload")
    return payload if isinstance(payload, dict) else {}


def _sender_role(content: dict[str, Any]) -> str | None:
    env = content.get("l9")
    if not isinstance(env, dict):
        return None
    actors = env.get("header", {}).get("participants", {}).get("actors")
    if isinstance(actors, list) and actors and isinstance(actors[0], dict):
        role = actors[0].get("role")
        return role if isinstance(role, str) else None
    return None


class AlignerEngine:
    """The dormant, summon-driven SIEP aligner (one per backend process).

    Holds no state between summons beyond the set of rooms it is actively
    judging (so a second summon can't spawn a duplicate run over the same room).
    Reaches the channel, transcript, and episode lifecycle through the
    :class:`RoomChannelManager` it is wired to.
    """

    def __init__(
        self,
        manager: RoomChannelManager,
        *,
        handle: str | None = None,
        threshold: float | None = None,
        max_rounds: int | None = None,
        round_timeout_s: float | None = None,
        poll_interval_s: float | None = None,
        max_steps: int | None = None,
        llm_session_factory: Callable[[str], Callable[..., str]] | None = None,
    ) -> None:
        self._manager = manager
        self._handle = handle if handle is not None else settings.ALIGNER_HANDLE
        self._threshold = threshold if threshold is not None else settings.ALIGNER_THRESHOLD
        self._max_rounds = max_rounds if max_rounds is not None else settings.ALIGNER_MAX_ROUNDS
        self._round_timeout_s = (
            round_timeout_s if round_timeout_s is not None else settings.ALIGNER_ROUND_TIMEOUT_S
        )
        self._poll_interval_s = (
            poll_interval_s if poll_interval_s is not None else settings.ALIGNER_POLL_INTERVAL_S
        )
        self._max_steps = (
            max_steps if max_steps is not None else settings.ALIGNER_MEDIATOR_MAX_STEPS
        )
        # Builds the mediator's llm_session (an *internal* Pi agent) per episode. Default
        # (None) → a fresh per-episode :class:`~app.services.pi_session.PiSession`; tests
        # inject a fake. Only the engine's own LLM session — user participant agents are
        # unaffected. See ``_open_llm_session``.
        self._llm_session_factory = llm_session_factory
        # Rooms with a run in flight — a re-summon while active is ignored.
        self._active: set[str] = set()
        # Strong refs to scheduled runs so they aren't GC'd mid-flight.
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def handle(self) -> str:
        return self._handle

    # -- the summon seam (sync; called from the persister's on_summon) --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: L9,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        """Fire the aligner when a registered ``engine`` (kind ``aligner``) — or
        the legacy reserved handle — is summoned; else ignore.

        The persister fires this for every ``@``-mention, so the identity gate is
        what keeps an ``@teammate`` from spawning an engine.
        The aligner is a first-class registered agent: a summon of a handle whose
        manifest is ``adapter=engine, kind=aligner`` runs *as that handle*. The
        reserved ``ALIGNER_HANDLE`` stays a back-compat fallback.
        A self-authored envelope never re-summons; a room already active is left
        alone.
        """
        is_reserved = _norm(handle) == _norm(self._handle)
        if not is_reserved and _registered_engine_kind(room, handle) != "aligner":
            return
        # When ENGINE_RUNTIME=host the host daemon owns a *registered* engine's
        # run (it drives NEGMAS where `pi` lives), so the backend must not also
        # mediate or the negotiation double-runs. The reserved ALIGNER_HANDLE
        # fallback has no host manifest, so it always runs backend-side regardless.
        if not is_reserved and settings.ENGINE_RUNTIME == "host":
            logger.info(
                "engine @%s summoned in %s but ENGINE_RUNTIME=host — host daemon owns the run",
                handle,
                room,
            )
            return
        from app.services.persister import envelope_sender

        sender = envelope_sender(envelope)
        if sender is not None and _norm(sender) in {_norm(self._handle), _norm(handle)}:
            return  # never summon off our own message
        if room in self._active:
            logger.debug("aligner already active on room %s; ignoring re-summon", room)
            return
        self._active.add(room)
        scoped = self._scoped_participants(handle, co_summons)
        task = asyncio.create_task(self._run_and_release(room, handle, scoped))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _scoped_participants(
        self, engine_handle: str, co_summons: list[str] | None
    ) -> list[str] | None:
        """The participant subset a scoped summon named, or ``None`` for everyone.

        A bare ``@aligner`` (or a summon naming only the engine) negotiates every
        room member. ``@aligner @a @b`` scopes the run to @a/@b — the engine handle
        and non-participants are dropped. An empty result falls back to ``None``
        (all members) so a mis-parse never yields a zero-participant negotiation.
        """
        if not co_summons:
            return None
        drop = {_norm(engine_handle), _norm(self._handle), *(_norm(h) for h in _NON_PARTICIPANTS)}
        scoped = [h for h in co_summons if _norm(h) not in drop]
        return scoped or None

    async def _run_and_release(
        self, room: str, engine_handle: str, scoped_participants: list[str] | None = None
    ) -> None:
        # A summon always drives a live NEGMAS SAO, running *as* the summoned
        # engine handle. There is one path — mediate — no mode to choose.
        try:
            await self.mediate(
                room, engine_handle=engine_handle, scoped_participants=scoped_participants
            )
        except Exception:
            logger.exception("aligner run failed on room %s", room)
        finally:
            self._active.discard(room)

    # -- mediator mode (drive a real NEGMAS SAO over SLIM) --

    async def mediate(
        self,
        room: str,
        engine_handle: str | None = None,
        scoped_participants: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Run a NEGMAS SAO negotiation live over SLIM, terminating at agreement.

        Runs *as* ``engine_handle`` — the registered ``engine`` (kind ``aligner``)
        that was summoned — so that handle is excluded from the participant roster
        it addresses (an engine must never ``@``-address itself). Falls back to the
        legacy reserved handle when summoned that way.

        The replacement for the passive observer: on summon, discover the issues
        from the agents' opening prose, then let NEGMAS drive the rounds —
        ``@``-addressing one agent at a time over the channel, interpreting the
        real reply, and stopping the *instant* the mechanism reaches unanimity
        (the anti-theater property). Hands the agreed ``issue = value`` map to the
        same ``commit:converged`` seam ``task_sync`` already consumes.

        NEGMAS is synchronous, so ``mech.run()`` executes on a worker thread; each
        negotiator bridges back to this loop for its SLIM turn (see
        :mod:`app.services.mediator`). Always closes the episode in ``finally`` so
        deferred invites drain even on a mid-run failure.
        """
        from app.services import mediator

        managed = self._manager.get(room)
        if managed is None or managed.persister is None:
            logger.info("aligner (mediator) summoned for %s but no live channel/persister", room)
            return None
        persister = managed.persister
        me = engine_handle or self._handle
        participants = self._roster(room, me)
        if scoped_participants:
            scoped = {_norm(h) for h in scoped_participants}
            participants = [m for m in participants if _norm(m) in scoped]
            logger.info("aligner (mediator) room %s scoped to %s", room, participants)

        # Nothing to broker: a negotiation needs at least two participants that are
        # present with opening positions. Rather than open a throwaway episode and
        # reject it in silence — leaving whoever summoned the aligner with no
        # feedback at all — let the LLM session explain, in its own words, why it can't
        # align and what to do next.
        if len(participants) < 2:
            logger.info(
                "aligner (mediator) room %s: %d participant(s) present — nothing to align",
                room,
                len(participants),
            )
            await self._explain_stall(managed, room, me, participants)
            return None

        episode_id = _new_episode_id()
        episode = l9.episode_urn(room, episode_id)
        topic = l9.topic_urn(room)

        self._manager.open_episode(room, episode)
        positions = self._opening_positions(persister, participants)
        ep = l9_episode.open_episode(
            parent_room=room,
            short_id=episode_id,
            workspace_id=managed.workspace,
            mas_id="",
            agents=participants,
            joined_intents="aligner mediate: converge on the open question via SAO",
            engine_handle=me,
            opening_positions=positions,
        )
        try:
            llm_session = self._signalling(self._open_llm_session(episode), room, episode)
            positions = await self._clarify_terms(
                managed, persister, ep, me, episode, topic, positions, llm_session
            )
            issues = await asyncio.to_thread(
                mediator.discover_issues,
                "Converge on the room's open question — agree one value per issue.",
                positions,
                llm=llm_session,
            )
            if not issues:
                logger.info("aligner (mediator) room %s: no issues discovered; rejecting", room)
                return await self._emit_verdict(
                    managed,
                    ep,
                    {},
                    converged=False,
                    metrics=None,
                    text="✗ not converged — could not structure the discussion into issues.",
                )

            ep.issue_options = {i["name"]: [str(o) for o in i["options"]] for i in issues}
            loop = asyncio.get_running_loop()
            negotiation = mediator.MediatedNegotiation(
                issues=issues,
                cap=self._max_steps,
                loop=loop,
                fetch_prose=lambda handle, prompt, round_n: self._slim_turn(
                    managed, persister, me, handle, episode, topic, prompt, round_n
                ),
                turn_timeout_s=self._round_timeout_s,
                llm=llm_session,
                on_reading=lambda handle, reading, proposing: self._fold_reading(
                    ep, handle, reading, proposing
                ),
            )
            mech = mediator.build_mechanism(issues, participants, negotiation, cap=self._max_steps)
            await asyncio.to_thread(mech.run)

            assignments = mediator.agreement_assignments(mech, negotiation.names)
            converged = assignments is not None
            _, metrics = self._verdict(ep)
            # Post-hoc satisfaction: how close the agreed outcome sits to
            # each agent's opening ask, and the room minimum — the least-happy
            # agent. Independent of MPC/GAR/SCR (which need stated confidence the
            # mediated path rarely has), so it rides alongside in ``metrics``.
            if converged and assignments:
                satisfaction = l9_episode.estimate_satisfaction(
                    ep.opening_offers, assignments, ep.issue_options
                )
                if satisfaction:
                    metrics = dict(metrics or {})
                    metrics["satisfaction"] = satisfaction
                    metrics["min_satisfaction"] = round(min(satisfaction.values()), 4)
            logger.info(
                "aligner (mediator) room %s → %s in %d steps (%s)",
                room,
                "agreement" if converged else "no agreement",
                mech.current_step,
                assignments,
            )
            return await self._emit_verdict(
                managed,
                ep,
                assignments or {},
                converged=converged,
                metrics=metrics,
                text=self._mediator_text(converged, assignments, mech.current_step),
            )
        finally:
            await self._manager.close_episode(room)

    def _open_llm_session(self, episode: str) -> Callable[..., str]:
        """Build the mediator's LLM session for this negotiation — always a Pi agent.

        Default: a fresh :class:`~app.services.pi_session.PiSession` bound to a
        per-episode ``--session`` file so the *internal* agent keeps real memory
        across SAO rounds (the anti-theater property — the mediator remembers the
        whole haggle, not a stateless call per turn). A test injects a fake via
        ``llm_session_factory``. Only the engine's own LLM session; user participant agents are
        untouched (they answer over SLIM/HTTP as before). Callers wrap the result
        in :meth:`_signalling` before the mediator sees it.
        """
        if self._llm_session_factory is not None:
            return self._llm_session_factory(episode)
        return self._pi_session(episode)

    def _signalling(
        self, session: Callable[..., str], room: str, episode: str
    ) -> Callable[..., str]:
        """Bracket every call through ``session`` with the activity signal.

        The room sees "@aligner is responding…" for exactly the seconds Pi is
        generating and nothing else — not the whole negotiation, most of which
        is waiting on the agents (:mod:`app.services.activity`). The mediator
        calls the session from a worker thread (``asyncio.to_thread``,
        ``mech.run``), so the signal is handed back to the loop rather than
        published from the thread.
        """
        loop = asyncio.get_running_loop()
        me = self._handle

        def call(*args: Any, **kwargs: Any) -> str:
            loop.call_soon_threadsafe(
                functools.partial(activity.signal, room, me, "responding", episode=episode)
            )
            try:
                return session(*args, **kwargs)
            finally:
                loop.call_soon_threadsafe(
                    functools.partial(activity.signal, room, me, "done", episode=episode)
                )

        return call

    def _pi_session(self, episode: str) -> Callable[..., str]:
        import tempfile
        from pathlib import Path

        from app.services.pi_session import PiSession

        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", episode).strip("-") or "align"
        session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        return PiSession(
            session_path=session_dir / f"{slug}.jsonl",
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            binary=settings.ALIGNER_PI_BINARY,
            timeout_s=settings.ALIGNER_PI_TIMEOUT_S,
            openshell=settings.ALIGNER_PI_OPENSHELL,
        )

    def _roster(self, room: str, me: str) -> list[str]:
        """The agents this run may broker between: ``room``'s registered roster.

        The union of the room's **registered** agents and whoever is currently
        connected — because each set alone misses real participants.

        ``members()`` answers "who holds a live SLIM socket or presence lease
        right now", which is connectivity, not membership: an agent parked in a
        herdr pane, or simply between turns, is a full member of the room that
        ``members()`` omits. Brokering is not delivery — a mention wakes a herdr
        pane and otherwise waits on the durable cursor, and every round already
        has its own turn window — so gating the run on who happened to be
        connected at summon time rejected rooms well able to negotiate.

        The registry alone is not enough either: ``await``/``respond`` let any
        awake caller join without ``agent create``, so a connected participant
        may have no manifest at all.

        Engines are excluded — the aligner brokers between teammates, and an
        engine (itself, the synthesizer) is never a party to the deal.
        """
        from app.services.agent_registry import room_agents

        drop = {_norm(me), _norm(self._handle), *(_norm(h) for h in _NON_PARTICIPANTS)}
        roster: dict[str, str] = {}
        for agent in room_agents(room):
            if _norm(agent.handle) in drop or agent.adapter == "engine":
                continue
            roster[_norm(agent.handle)] = agent.handle
        for handle in self._manager.members(room):
            if _norm(handle) in drop:
                continue
            roster.setdefault(_norm(handle), handle)
        return [roster[k] for k in sorted(roster)]

    def _opening_positions(
        self, persister: RoomPersister, participants: list[str]
    ) -> dict[str, str]:
        """Each participant's most recent opening prose from the transcript.

        The issue-discovery seed. Falls back to a bare handle stub for any agent
        that has not yet spoken, so discovery still sees the full roster.
        """
        wanted = {_norm(p): p for p in participants}
        latest: dict[str, str] = {}
        for record in persister.log.records:
            if not self._is_position(record):
                continue
            key = _norm(record.sender)
            if key in wanted:
                text = record.content.get("content")
                if isinstance(text, str) and text.strip():
                    latest[wanted[key]] = text.strip()
        for handle in participants:
            latest.setdefault(handle, f"(no opening position stated by @{handle})")
        return latest

    async def _clarify_terms(
        self,
        managed: ManagedRoomChannel,
        persister: RoomPersister,
        ep: NegotiationState,
        sender: str,
        episode: str,
        topic: str,
        positions: dict[str, str],
        llm_session: Callable[..., str],
    ) -> dict[str, str]:
        """Stage 0 — one clarifying round when agents share a term but not its meaning.

        Agents can converge on words they read differently ("priority", "done",
        "blocked"), and an agreement built on those words settles nothing. So
        before any offer exists, the LLM session reads the opening prose for terms two
        participants are using in different senses; when it finds any, each
        participant is ``@``-addressed once — the same one-agent-at-a-time seam the
        SAO rounds use — and its answer is folded into the prose that issue
        discovery then reads.

        Exactly one round, never a loop: the point is to make the vocabulary
        visible to the mediator and the room, not to negotiate the definitions.
        No mismatch (the common case) means no prompt and no reply wait, so a room
        that speaks the same language runs exactly as it did before.

        The returned positions are what the negotiation proceeds on; the episode
        keeps the untouched opening snapshot, so the record still shows what each
        agent said before it was asked to define anything.
        """
        from app.services import mediator

        if not settings.ALIGNER_TERM_CHECK:
            return positions
        try:
            mismatches = await asyncio.to_thread(
                mediator.detect_term_mismatch, positions, llm=llm_session
            )
        except Exception:
            logger.warning("aligner term check failed on room %s", managed.room, exc_info=True)
            return positions
        if not mismatches:
            return positions
        logger.info(
            "aligner (mediator) room %s: term mismatch on %s — one clarifying round",
            managed.room,
            [m["term"] for m in mismatches],
        )
        clarified = dict(positions)
        clarifications: dict[str, str] = {}
        for handle in positions:
            reply = await self._slim_turn(
                managed,
                persister,
                sender,
                handle,
                episode,
                topic,
                mediator.clarification_prompt(handle, mismatches),
                _CLARIFY_ROUND,
                action="clarify",
            )
            text = reply.strip()
            if not text:
                continue  # silence leaves that agent's opening prose as stated
            clarifications[handle] = text
            clarified[handle] = f"{positions[handle]}\n\n(clarified by @{handle}: {text})"
        l9_episode.record_term_check(ep, mismatches=mismatches, clarifications=clarifications)
        return clarified

    async def _slim_turn(
        self,
        managed: ManagedRoomChannel,
        persister: RoomPersister,
        sender: str,
        handle: str,
        episode: str,
        topic: str,
        prompt: str,
        round_n: int,
        action: str = "position",
    ) -> str:
        """Publish one ``@handle`` prompt, wait for the reply, return its prose.

        Bounded by ``round_timeout_s`` (a silent agent yields ``""``, read as a
        reject) so the mechanism can never hang on one participant. ``action`` is
        what the tick asks for: an SAO ``position``, or a ``clarify`` definition on
        the pre-negotiation round.
        """
        before = len(persister.log.records)
        env = l9.build_envelope(
            kind=l9.Kind.exchange,
            episode=episode,
            sender=sender,
            recipients=[handle],
            topic=topic,
            payload_type="tick",
            payload_data={"round": round_n, "action": action},
        )
        # Neutralize ``@`` tokens so the broker's summary (which names the other
        # agents) doesn't spuriously wake them — only the L9 ``recipients=[handle]``
        # above should wake, one agent per turn.
        safe_prompt = _AT_MENTION.sub("", prompt)
        # Record the mediator's turn-prompt into the room transcript + UI bus, the
        # same way ``publish_human`` records a human's message. Without this the
        # negotiation is invisible in the room (the prompt only rides SLIM), so
        # humans can't follow along and debugging falls back to backend logs. The
        # persister de-dupes by id, so a SLIM loop-back to the sender is harmless.
        try:
            await managed.post(env, safe_prompt, raise_on_send_failure=True)
        except Exception:
            logger.warning("mediator failed to prompt @%s (step %d)", handle, round_n)
            return ""

        pending = _norm(handle)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._round_timeout_s
        while True:
            for record in persister.log.records[before:]:
                if self._is_position(record) and _norm(record.sender) == pending:
                    return record.content.get("content") or ""
            if loop.time() >= deadline:
                return ""
            await asyncio.sleep(self._poll_interval_s)

    async def _explain_stall(
        self, managed: ManagedRoomChannel, room: str, sender: str, participants: list[str]
    ) -> None:
        """Post the aligner's own account of why it can't align yet.

        The LLM session writes the message so it reads naturally and in context (not a
        canned string); a static line is the fail-soft fallback when the LLM session is
        unavailable. Either way the room gets a plain, actionable reply instead of
        silence.
        """
        roster = ", ".join(participants) if participants else "no other agents"
        prompt = (
            "You are this room's alignment mediator, just summoned to help it align, "
            "but you cannot run a negotiation right now: brokering needs at least two "
            "agents registered in the room besides you, and the room's roster is: "
            f"{roster}. Write a short, friendly message to the room (2-3 sentences) that "
            "explains you can't align yet and says what to do next — register a second "
            "agent in this room (e.g. with 'mycelium agent create <handle> --room "
            "<room>'), then summon you again. Plain prose, no @-mentions."
        )
        text = ""
        try:
            one_shot = l9.episode_urn(room, _new_episode_id())
            llm_session = self._signalling(self._open_llm_session(one_shot), room, one_shot)
            text = (await asyncio.to_thread(llm_session, prompt) or "").strip()
        except Exception:
            logger.warning(
                "aligner LLM session unavailable to explain stall in %s", room, exc_info=True
            )
        if not text:
            text = (
                "I can't align the room yet — brokering needs at least two agents "
                "registered here besides me. Add another agent to the room, then "
                "summon me again."
            )
        await self._say(managed, room, sender, text)

    async def _say(self, managed: ManagedRoomChannel, room: str, sender: str, text: str) -> None:
        """Broadcast a plain message from the aligner (not a verdict envelope). Any
        ``@`` tokens are stripped so the notice can't spuriously summon anyone."""
        safe = _AT_MENTION.sub("", text)
        env = l9.build_envelope(
            kind=l9.Kind.exchange,
            episode=l9.episode_urn(room, "live"),
            sender=sender,
            topic=l9.topic_urn(room),
            payload_type="message",
        )
        await managed.post(env, safe)

    def _fold_reading(
        self, ep: NegotiationState, handle: str, reading: dict[str, Any], proposing: bool
    ) -> None:
        """Fold one interpreted SAO move into the episode so metrics stay live.

        The mediated path's replies are prose, not epistemic payloads, so we
        synthesize a ``record_reply`` shape from the mediator's own reading — the
        L9 episode record and the consensus envelope's MPC/GAR/SCR are then
        computed over what the mediator actually understood.
        """
        if not isinstance(reading, dict):
            return
        reply: dict[str, Any] = {}
        action = reading.get("action")
        if isinstance(action, str) and action:
            reply["action"] = "accept" if action == "accept" else "reject"
        offer = reading.get("offer")
        if isinstance(offer, dict):
            reply["offer"] = offer
            reply.setdefault("action", "accept" if proposing else "reject")
            # The agent's first concrete offer is its opening ask — the baseline
            # #682 scores the agreed outcome's satisfaction against.
            ep.opening_offers.setdefault(handle, {k: str(v) for k, v in offer.items()})
        # The wire move type, kept distinct from the collapsed metric ``action``
        # above: the mediator's raw verb when it's one of the closed vocabulary,
        # else a bare offer is a ``counter`` (the opening position included).
        if isinstance(action, str) and action in l9.EXCHANGE_MOVE_SUBKINDS:
            reply["move"] = action
        elif isinstance(offer, dict):
            reply["move"] = "counter"
        l9_episode.record_reply(ep, handle=handle, reply=reply, round_n=None)

    def _mediator_text(
        self, converged: bool, assignments: dict[str, str] | None, steps: int
    ) -> str:
        """The human-facing summary the agents read on a mediated verdict."""
        if converged and assignments:
            terms = " · ".join(f"{issue} = {value}" for issue, value in assignments.items())
            return f"✓ agreement in {steps} steps — {terms}."
        return f"✗ no agreement — the negotiation ran {steps} steps without unanimity."

    # -- scoring (delegates the math to l9_episode) --

    def _is_position(self, record: TranscriptRecord) -> bool:
        """True when a transcript record is an agent's position (not noise).

        Counts an ``exchange`` from an agent (role != human) that is not the
        engine/backend/system and not a bare presence hello. Everything the
        metrics fold over passes through here.
        """
        if record.kind != "exchange":
            return False
        if _payload(record.content).get("type") == "presence":
            return False
        if _sender_role(record.content) == "human":
            return False
        sender = record.sender
        return bool(sender) and _norm(sender) not in {
            _norm(self._handle),
            *(_norm(h) for h in _NON_PARTICIPANTS),
        }

    def _verdict(self, ep: NegotiationState) -> tuple[bool, dict[str, Any] | None]:
        """(converged, metrics). Converged ⇔ metrics exist and MPC ≥ threshold."""
        metrics = l9_episode.compute_metrics(ep)
        converged = metrics is not None and metrics["mpc"] >= self._threshold
        return converged, metrics

    # -- emitting the verdict --

    async def _emit_verdict(
        self,
        managed: ManagedRoomChannel,
        ep: NegotiationState,
        assignments: dict[str, Any],
        converged: bool,
        metrics: dict[str, Any] | None,
        text: str | None = None,
    ) -> dict[str, Any]:
        """Broadcast the ``commit`` envelope and record it once locally.

        Emitting a ``commit:converged`` here is exactly the plan-compile trigger
        the persister watches — ``on_converged`` is wired to ``task_compiler``.
        """
        env_dict = l9_episode.build_consensus_envelope(
            ep, broken=not converged, assignments=assignments, metrics=metrics
        )
        # The verdict is a *broadcast* terminal statement. Its record-side parents
        # (built above: the episode's synthesized reply ids) are never on the
        # wire, and no single on-channel message is delivered to *every* member
        # (a group broadcast is not echoed to its own sender), so any wire parent
        # would leave some receiver's CausalOrderBuffer holding the commit
        # forever. Emit with empty wire parents — releasable by everyone — while
        # the full causal chain stays intact in the episode record (ep.messages).
        wire_dict = copy.deepcopy(env_dict)
        wire_dict["header"]["message"]["parents"] = []
        envelope = l9.parse_envelope(wire_dict)
        if text is None:
            text = self._verdict_text(converged, metrics)
        # Record + trigger locally (deduped by message id), so the transcript,
        # UI bus, and on_converged seam fire even if SLIM never loops our own
        # broadcast back to the moderator (mirrors the human-proxy publish).
        await managed.post(envelope, text)
        l9_episode.write_episode_record(
            ep,
            outcome="converged" if converged else "rejected",
            metrics=metrics,
            tasks=None,
        )
        return env_dict

    def _verdict_text(self, converged: bool, metrics: dict[str, Any] | None) -> str:
        """The human-facing summary agents read (must carry no ``@handle``)."""
        if metrics is None:
            return "✗ not converged — insufficient participation to score alignment."
        digest = (
            f"MPC {metrics['mpc']:.2f} · GAR {metrics['gar']:.2f} · "
            f"SCR {metrics['scr']:.2f} over {metrics['participants']} participants"
        )
        if converged:
            return f"✓ converged — {digest}."
        return f"✗ not converged — {digest} (MPC below threshold {self._threshold:.2f})."
