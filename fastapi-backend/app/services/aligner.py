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
*instant* the mechanism reaches unanimity (the anti-theatre property). It hands
the agreed ``issue = value`` map to the ``commit:converged`` seam ``plan_sync``
consumes (a failed run commits ``rejected``). Deterministic scoring (MPC/GAR/SCR)
still rides along via :mod:`l9_episode`, computed over the mediator's readings.

**Runtime note.** This runs **in-process in the backend** — the ``commit``
envelope is emitted onto the channel the backend moderates, and the mediator's own
brain is a Pi agent (:mod:`app.services.pi_brain`, always Pi). Participants answer
over the channel however they run (a daemon cold-spawn, or a server-held CLI
``await``/``respond`` caller) — the engine only ``@``-addresses them; it never
spawns a judge of its own.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services import l9, l9_episode
from app.services.l9_slim import serialize_content
from app.services.room_channels import BACKEND_AGENT

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.services.l9_episode import EpisodeState
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
# spuriously wake *every* named agent, doubling cold-spawns and serialising the
# connectors until the addressed agent's real reply misses the round window (the
# turn then falls back to a reject). Neutralising the ``@`` means only the
# L9-addressed agent wakes; the names stay readable.
_AT_MENTION = re.compile(r"@(?=\w)")


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
    """Case/space-fold a handle for identity comparison (matches the connector)."""
    return handle.strip().lower()


def _new_episode_id() -> str:
    """A short, unique, filesystem-safe id for one convening (one episode).

    Each ``@``-summon convenes a *distinct* episode. The id flows into the episode
    URN (``l9.episode_urn``), every envelope on the wire, and the
    ``log/episodes/{id}.md`` record filename — so two convenings in the same room
    never share a URN or clobber each other's record. Was a hardcoded constant
    (``"align"``); every negotiation then overwrote the one ``align.md``.
    """
    return uuid.uuid4().hex[:8]


def _payload(content: dict[str, Any]) -> dict[str, Any]:
    """The L9 payload dict of a recorded message's content (empty when absent)."""
    env = content.get("l9")
    if not isinstance(env, dict):
        return {}
    payload = env.get("payload")
    return payload if isinstance(payload, dict) else {}


def _sender_role(content: dict[str, Any]) -> str | None:
    """Role of the first actor (the sender) on a recorded message, if any."""
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
        brain_factory: Callable[[str], Callable[..., str]] | None = None,
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
        # Builds the mediator's brain (an *internal* Pi agent) per episode. Default
        # (None) → a fresh per-episode :class:`~app.services.pi_brain.PiBrain`; tests
        # inject a fake. Only the engine's own brain — user participant agents are
        # unaffected. See ``_make_brain``.
        self._brain_factory = brain_factory
        # Rooms with a run in flight — a re-summon while active is ignored.
        self._active: set[str] = set()
        # Strong refs to scheduled runs so they aren't GC'd mid-flight.
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def handle(self) -> str:
        return self._handle

    # -- the summon seam (sync; called from the persister's on_summon) --

    def handle_summon(
        self, room: str, handle: str, envelope: L9, co_summons: list[str] | None = None
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
        (the anti-theatre property). Hands the agreed ``issue = value`` map to the
        same ``commit:converged`` seam ``plan_sync`` already consumes.

        NEGMAS is synchronous, so ``mech.run()`` executes on a worker thread; each
        negotiator bridges back to this loop for its SLIM turn (see
        :mod:`app.services.mediator`). Always closes the episode in ``finally`` so
        queued invites drain even on a mid-run failure.
        """
        from app.services import mediator

        managed = self._manager.get(room)
        if managed is None or managed.persister is None:
            logger.info("aligner (mediator) summoned for %s but no live channel/persister", room)
            return None
        persister = managed.persister
        me = engine_handle or self._handle
        participants = [m for m in self._manager.members(room) if _norm(m) != _norm(me)]
        if scoped_participants:
            scoped = {_norm(h) for h in scoped_participants}
            participants = [m for m in participants if _norm(m) in scoped]
            logger.info("aligner (mediator) room %s scoped to %s", room, participants)
        episode_id = _new_episode_id()
        episode = l9.episode_urn(room, episode_id)
        topic = l9.topic_urn(room)

        self._manager.open_episode(room, episode)
        ep = l9_episode.open_episode(
            parent_room=room,
            short_id=episode_id,
            workspace_id=managed.workspace,
            mas_id="",
            agents=participants,
            joined_intents="aligner mediate: converge on the open question via SAO",
        )
        try:
            brain = self._make_brain(episode)
            positions = self._opening_positions(persister, participants)
            issues = await asyncio.to_thread(
                mediator.discover_issues,
                "Converge on the room's open question — agree one value per issue.",
                positions,
                llm=brain,
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

            loop = asyncio.get_running_loop()
            negotiation = mediator.MediatedNegotiation(
                issues=issues,
                cap=self._max_steps,
                loop=loop,
                fetch_prose=lambda handle, prompt, round_n: self._slim_turn(
                    managed, persister, handle, episode, topic, prompt, round_n
                ),
                turn_timeout_s=self._round_timeout_s,
                llm=brain,
                on_reading=lambda handle, reading, proposing: self._fold_reading(
                    ep, handle, reading, proposing
                ),
            )
            mech = mediator.build_mechanism(issues, participants, negotiation, cap=self._max_steps)
            await asyncio.to_thread(mech.run)

            assignments = mediator.agreement_assignments(mech, negotiation.names)
            converged = assignments is not None
            _, metrics = self._verdict(ep)
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

    def _make_brain(self, episode: str) -> Callable[..., str]:
        """Build the mediator's brain for this negotiation — always a Pi agent.

        Default: a fresh :class:`~app.services.pi_brain.PiBrain` bound to a
        per-episode ``--session`` file so the *internal* agent keeps real memory
        across SAO rounds (the anti-theatre property — the mediator remembers the
        whole haggle, not a stateless call per turn). A test injects a fake via
        ``brain_factory``. Only the engine's own brain; user participant agents are
        untouched (they answer over SLIM/HTTP as before).
        """
        if self._brain_factory is not None:
            return self._brain_factory(episode)

        import tempfile
        from pathlib import Path

        from app.services.pi_brain import PiBrain

        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", episode).strip("-") or "align"
        session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        return PiBrain(
            session_path=session_dir / f"{slug}.jsonl",
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            binary=settings.ALIGNER_PI_BINARY,
            timeout_s=settings.ALIGNER_PI_TIMEOUT_S,
            openshell=settings.ALIGNER_PI_OPENSHELL,
        )

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

    async def _slim_turn(
        self,
        managed: ManagedRoomChannel,
        persister: RoomPersister,
        handle: str,
        episode: str,
        topic: str,
        prompt: str,
        round_n: int,
    ) -> str:
        """Publish one ``@handle`` prompt, wait for the reply, return its prose.

        Bounded by ``round_timeout_s`` (a silent agent yields ``""``, read as a
        reject) so the mechanism can never hang on one participant.
        """
        before = len(persister.log.records)
        env = l9.build_envelope(
            kind=l9.Kind.exchange,
            episode=episode,
            recipients=[handle],
            topic=topic,
            payload_type="tick",
            payload_data={"round": round_n, "action": "position"},
        )
        # Neutralise ``@`` tokens so the broker's summary (which names the other
        # agents) doesn't spuriously wake them — only the L9 ``recipients=[handle]``
        # above should wake, one agent per turn.
        safe_prompt = _AT_MENTION.sub("", prompt)
        content = serialize_content(env, extra={"content": safe_prompt})
        try:
            await managed.channel.send(env, extra={"content": safe_prompt})
        except Exception:
            logger.warning("mediator failed to prompt @%s (step %d)", handle, round_n)
            return ""
        # Record the mediator's turn-prompt into the room transcript + UI bus, the
        # same way ``publish_human`` records a human's message. Without this the
        # negotiation is invisible in the room (the prompt only rides SLIM), so
        # humans can't follow along and debugging falls back to backend logs. The
        # persister de-dupes by id, so a SLIM loop-back to the sender is harmless.
        persister.ingest_local(env, content)

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

    def _fold_reading(
        self, ep: EpisodeState, handle: str, reading: dict[str, Any], proposing: bool
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

    def _verdict(self, ep: EpisodeState) -> tuple[bool, dict[str, Any] | None]:
        """(converged, metrics). Converged ⇔ metrics exist and MPC ≥ threshold."""
        metrics = l9_episode.compute_metrics(ep)
        converged = metrics is not None and metrics["mpc"] >= self._threshold
        return converged, metrics

    # -- emitting the verdict --

    async def _emit_verdict(
        self,
        managed: ManagedRoomChannel,
        ep: EpisodeState,
        assignments: dict[str, Any],
        converged: bool,
        metrics: dict[str, Any] | None,
        text: str | None = None,
    ) -> dict[str, Any]:
        """Broadcast the ``commit`` envelope and record it once locally.

        Emitting a ``commit:converged`` here is exactly the plan-compile trigger
        the persister watches — ``on_converged`` is wired to ``plan_compiler``.
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
        content = serialize_content(envelope, extra={"content": text})
        try:
            await managed.channel.send(envelope, extra={"content": text})
        except Exception:
            logger.warning("aligner failed to broadcast verdict on room %s", managed.room)
        # Record + trigger locally (deduped by message id), so the transcript,
        # UI bus, and on_converged seam fire even if SLIM never loops our own
        # broadcast back to the moderator (mirrors the human-proxy publish).
        if managed.persister is not None:
            managed.persister.ingest_local(envelope, content)
        l9_episode.write_episode_record(
            ep,
            outcome="converged" if converged else "rejected",
            metrics=metrics,
            plan_file=None,
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
