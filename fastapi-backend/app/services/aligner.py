# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The SIEP aligner — the first cognition engine (Step 7, bible §10).

Bible §10 splits three things that used to be bundled as "the CE":

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

**Two modes, once summoned:**

- **Observer (one-shot):** read the room transcript, replay each participant's
  exchange through :mod:`l9_episode`'s metric folding, score, and emit an L9
  ``commit:converged`` (MPC ≥ threshold) or ``commit:rejected`` (below) onto the
  channel — then sleep.
- **Driver (takes the wheel):** open an episode (freezing membership), then run
  up to *N* rounds — prompt each participant for a position on the channel (which
  wakes their Step 5 connector), collect the replies the persister records,
  fold + score — stopping on convergence or the round cap, then emit the verdict
  and close the episode (which drains any invites Step 6 queued mid-episode).

**Runtime note (the Step 7 open question).** The default the bible names is "a
cold-spawned agent turn, reusing ``spawn.py``". The verdict itself — the metrics
and the ``commit`` envelope — is inherently backend-side (it is deterministic
math over the transcript the backend already holds, emitted onto the channel the
backend moderates), and the CLI's ``integration.spawn`` is not reachable from the
backend process. So this engine runs **in-process in the backend** and reuses the
cold-spawn runtime the way the bible means it: the **driver** prompts participants
by publishing on the channel, and their existing Step 5 connectors cold-spawn the
turn and reply. The engine drives the participants' spawns rather than spawning a
judge of its own. The base-level verdict needs no LLM of its own — it is the
threshold decision over the deterministic library — which also keeps the spawn
cold. (Flagged in the Step 8 handoff; an LLM judgment/summary layer is post-MVP.)
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services import l9, l9_episode
from app.services.l9_slim import serialize_content
from app.services.room_channels import BACKEND_AGENT

if TYPE_CHECKING:
    from app.services.l9_episode import EpisodeState
    from app.services.l9_models import L9
    from app.services.persister import RoomPersister, TranscriptRecord
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)

MODE_OBSERVER = "observer"
MODE_DRIVER = "driver"

# Handles that are never a participant position: the engine itself, the backend
# moderator, and the system actor the backend signs its own envelopes with.
_NON_PARTICIPANTS = frozenset({BACKEND_AGENT, l9.SYSTEM_ACTOR_ID})

# Epistemic fields the aligner reads off an exchange's L9 payload and hands to
# ``l9_episode.record_reply`` verbatim (it validates/clamps each one).
_EPISTEMIC_KEYS = (
    "confidence",
    "offer",
    "evidence",
    "supporting_evidence",
    "against_evidence",
    "addresses",
    "revision_cause",
    "deferred_to",
    "reasoning",
)


def _norm(handle: str) -> str:
    """Case/space-fold a handle for identity comparison (matches the connector)."""
    return handle.strip().lower()


def _payload(content: dict[str, Any]) -> dict[str, Any]:
    """The L9 payload dict of a recorded message's content (empty when absent)."""
    env = content.get("l9")
    if not isinstance(env, dict):
        return {}
    payload = env.get("payload")
    return payload if isinstance(payload, dict) else {}


def _payload_data(content: dict[str, Any]) -> dict[str, Any]:
    data = _payload(content).get("data")
    return data if isinstance(data, dict) else {}


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


def reply_from_content(content: dict[str, Any]) -> dict[str, Any]:
    """Extract a ``record_reply``-shaped position from a recorded exchange.

    The epistemic signals ride the exchange's L9 payload ``data`` (where the
    connector and ``record_tick``/``record_reply`` put them). Only the fields
    ``l9_episode`` understands are copied; it re-validates each, so garbage is
    dropped there, not here. A missing ``action`` defaults to ``reject`` inside
    ``record_reply``.
    """
    data = _payload_data(content)
    reply: dict[str, Any] = {}
    action = data.get("action")
    if isinstance(action, str) and action:
        reply["action"] = action
    for key in _EPISTEMIC_KEYS:
        if key in data:
            reply[key] = data[key]
    return reply


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
        mode: str | None = None,
        threshold: float | None = None,
        max_rounds: int | None = None,
        round_timeout_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> None:
        self._manager = manager
        self._handle = handle if handle is not None else settings.ALIGNER_HANDLE
        self._mode = mode if mode is not None else settings.ALIGNER_MODE
        self._threshold = threshold if threshold is not None else settings.ALIGNER_THRESHOLD
        self._max_rounds = max_rounds if max_rounds is not None else settings.ALIGNER_MAX_ROUNDS
        self._round_timeout_s = (
            round_timeout_s if round_timeout_s is not None else settings.ALIGNER_ROUND_TIMEOUT_S
        )
        self._poll_interval_s = (
            poll_interval_s if poll_interval_s is not None else settings.ALIGNER_POLL_INTERVAL_S
        )
        # Rooms with a run in flight — a re-summon while active is ignored.
        self._active: set[str] = set()
        # Strong refs to scheduled runs so they aren't GC'd mid-flight.
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def handle(self) -> str:
        return self._handle

    # -- the summon seam (sync; called from the persister's on_summon) --

    def handle_summon(self, room: str, handle: str, envelope: L9) -> None:
        """Fire the engine when *its* reserved handle is summoned; else ignore.

        The persister fires this for every ``@``-mention in a message, so the
        identity gate here is what keeps an ``@teammate`` from spawning an engine
        (bible §10 / Step 7 trap). A self-authored envelope never re-summons, and
        a room already being judged is left alone.
        """
        if _norm(handle) != _norm(self._handle):
            return
        from app.services.persister import envelope_sender

        sender = envelope_sender(envelope)
        if sender is not None and _norm(sender) == _norm(self._handle):
            return  # never summon off our own message
        if room in self._active:
            logger.debug("aligner already active on room %s; ignoring re-summon", room)
            return
        self._active.add(room)
        task = asyncio.create_task(self._run_and_release(room))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(self, room: str) -> None:
        try:
            if self._mode == MODE_DRIVER:
                await self.drive(room)
            else:
                await self.observe(room)
        except Exception:
            logger.exception("aligner run failed on room %s", room)
        finally:
            self._active.discard(room)

    # -- observer mode --

    async def observe(self, room: str) -> dict[str, Any] | None:
        """Read the transcript, score it once, and emit a verdict. One-shot."""
        managed = self._manager.get(room)
        if managed is None or managed.persister is None:
            logger.info("aligner summoned for %s but no live channel/persister", room)
            return None
        records = managed.persister.log.records
        ep, assignments = self._episode_from_records(managed, records)
        converged, metrics = self._verdict(ep)
        logger.info(
            "aligner observed room %s → %s (%s)",
            room,
            "converged" if converged else "rejected",
            metrics,
        )
        return await self._emit_verdict(managed, ep, assignments, converged, metrics)

    # -- driver mode --

    async def drive(self, room: str) -> dict[str, Any] | None:
        """Run up to N rounds of prompt→collect→score, then emit a verdict.

        Opens an episode so a mid-run membership change aborts it (frozen
        membership, bible §9/§12); always closes it in ``finally`` so Step 6's
        queued invites drain even when a round times out.
        """
        managed = self._manager.get(room)
        if managed is None or managed.persister is None:
            logger.info("aligner (driver) summoned for %s but no live channel/persister", room)
            return None
        persister = managed.persister
        participants = [m for m in self._manager.members(room) if _norm(m) != _norm(self._handle)]
        episode = l9.episode_urn(room, "align")
        topic = l9.topic_urn(room)

        self._manager.open_episode(room, episode)
        ep = l9_episode.open_episode(
            parent_room=room,
            short_id="align",
            workspace_id=managed.workspace,
            mas_id="",
            agents=participants,
            joined_intents="aligner drive: converge on the open question",
        )
        assignments: dict[str, Any] = {}
        converged = False
        metrics: dict[str, Any] | None = None
        try:
            for round_n in range(1, self._max_rounds + 1):
                before = len(persister.log.records)
                await self._prompt_round(managed, participants, episode, topic, round_n)
                replies = await self._collect_round(persister, participants, before)
                for handle, record in replies.items():
                    self._fold(ep, assignments, handle, record, round_n)
                converged, metrics = self._verdict(ep)
                logger.info(
                    "aligner driver room %s round %d → %s (%s)",
                    room,
                    round_n,
                    "converged" if converged else "continuing",
                    metrics,
                )
                if converged:
                    break
            return await self._emit_verdict(managed, ep, assignments, converged, metrics)
        finally:
            await self._manager.close_episode(room)

    async def _prompt_round(
        self,
        managed: ManagedRoomChannel,
        participants: list[str],
        episode: str,
        topic: str,
        round_n: int,
    ) -> None:
        """Publish a per-participant position prompt (wakes their connector)."""
        for handle in participants:
            env = l9.build_envelope(
                kind=l9.Kind.exchange,
                episode=episode,
                recipients=[handle],
                topic=topic,
                payload_type="tick",
                payload_data={"round": round_n, "action": "position"},
            )
            text = (
                f"@{handle} — round {round_n}: state your position and confidence "
                f"(0.0-1.0) on the open question."
            )
            try:
                await managed.channel.send(env, extra={"content": text})
            except Exception:
                logger.warning("aligner failed to prompt @%s (round %d)", handle, round_n)

    async def _collect_round(
        self, persister: RoomPersister, participants: list[str], before: int
    ) -> dict[str, TranscriptRecord]:
        """Poll the transcript for each participant's latest post-prompt position.

        Bounded by ``round_timeout_s`` so a silent participant can never hang the
        loop; returns whatever arrived (possibly empty). Cheap: an async poll of
        the in-memory transcript, no LLM held open.
        """
        pending = {_norm(p) for p in participants}
        latest: dict[str, TranscriptRecord] = {}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._round_timeout_s
        while pending:
            for record in persister.log.records[before:]:
                if not self._is_position(record):
                    continue
                if _norm(record.sender) in pending:
                    latest[record.sender] = record
            pending -= {_norm(s) for s in latest}
            if not pending or loop.time() >= deadline:
                break
            await asyncio.sleep(self._poll_interval_s)
        return latest

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

    def _episode_from_records(
        self, managed: ManagedRoomChannel, records: list[TranscriptRecord]
    ) -> tuple[EpisodeState, dict[str, Any]]:
        """Replay the transcript's positions into a fresh episode + assignments."""
        positions = [r for r in records if self._is_position(r)]
        agents: list[str] = []
        for record in positions:
            if record.sender not in agents:
                agents.append(record.sender)
        ep = l9_episode.open_episode(
            parent_room=managed.room,
            short_id="live",
            workspace_id=managed.workspace,
            mas_id="",
            agents=agents,
            joined_intents="aligner observed exchange",
        )
        assignments: dict[str, Any] = {}
        for record in positions:
            self._fold(ep, assignments, record.sender, record, None)
        return ep, assignments

    def _fold(
        self,
        ep: EpisodeState,
        assignments: dict[str, Any],
        handle: str,
        record: TranscriptRecord,
        round_n: int | None,
    ) -> None:
        """Fold one position into the episode's metrics and the assignments map."""
        reply = reply_from_content(record.content)
        l9_episode.record_reply(ep, handle=handle, reply=reply, round_n=round_n)
        assignments[handle] = reply.get("offer") or reply.get("action") or "accept"

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
    ) -> dict[str, Any]:
        """Broadcast the ``commit`` envelope and record it once locally.

        Emitting a ``commit:converged`` here is exactly the plan-compile trigger
        the persister watches — Step 8 wires ``on_converged`` to ``plan_compiler``.
        Step 7 stops at emitting a correct, well-formed verdict.
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
