# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The conductor — the engine that runs a protocol inside a thread.

A fourth engine ``kind`` beside the aligner, the synthesizer and hello, and
the first with no model of its own. Summoned into a thread with the name of a
:mod:`~app.services.protocols` and the members to run it over, it walks that
protocol's steps in code: it holds the thread's floor for whoever the step
addresses, puts the step's prompt to them through the same one-agent turn the
aligner brokers with, reads the stance their reply took, and follows the edge.
Every judgment in a run — what to propose, whether to block it — is made by
the members it addresses. The conductor only decides who speaks next, and
that is the point: a model in the nodes, code on the edges.

What it shares with the other engines: dormant until a registered engine of
its kind is summoned, runs as that handle, and leaves a record at
``log/episodes/{id}.md``. What it does not share: it opens no negotiation,
so joining the room mid-run aborts nothing, and it never calls Pi.

Where it runs: in the thread it was summoned in. A summon from a task's
thread (``board coordinate <row> conductor "gated @a @b: …"``) runs there, so
the row's conversation carries the whole run and a person can answer a step
with ``board send``. A summon from the room itself opens a fresh thread,
since the room never holds a floor.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services import l9, l9_episode, markers, protocols, turns
from app.services.agent_registry import norm_handle
from app.services.aligner import _NON_PARTICIPANTS, _registered_engine_kind
from app.services.l9_models import Kind
from app.services.persister import record_episode
from app.services.tasks import mint_episode_id

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.persister import TranscriptRecord
    from app.services.protocols import Protocol, Step
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)

#: The engine kind this class owns.
ENGINE_KIND = "conductor"

#: Payloads that are never a member's answer to a step.
_NOT_A_REPLY = frozenset(
    {"presence", "keepalive", "tick", l9.PING_PAYLOAD_TYPE, l9.NOTICE_PAYLOAD_TYPE}
)

_MENTION = re.compile(r"@[\w.@-]+")
_LEADING_PUNCT = re.compile(r"^[\s:,;\u2014\u2013-]+")


def _norm(handle: str) -> str:
    return norm_handle(handle) or ""


def split_directive(text: str) -> tuple[str, str]:
    """``(protocol name, the ask)`` from a summon's text.

    The first word that is not a mention names the protocol; everything after
    it, mentions removed, is the ask the prompts carry as ``{ask}``.
    """
    words = _MENTION.sub(" ", text).split()
    if not words:
        return "", ""
    name = words[0].strip(":,;").lower()
    ask = _LEADING_PUNCT.sub("", " ".join(words[1:])).strip()
    return name, ask


class _Fields(dict[str, str]):
    """Template fields that render empty rather than raising when absent."""

    def __missing__(self, key: str) -> str:
        return ""


@dataclass
class Run:
    """One protocol run: what it is over, and what has been said in it."""

    protocol: Protocol
    ask: str
    handles: list[str]
    bound: dict[str, str]
    episode: str
    #: handle -> its most recent reply in this run.
    replies: dict[str, str] = field(default_factory=dict)
    #: The most recent reply anyone gave.
    recent: str = ""
    steps_taken: int = 0

    def targets(self, step: Step) -> list[str]:
        to = step.to or ""
        if to == "workers":
            named = set(self.bound.values())
            return [h for h in self.handles if h not in named]
        if to in protocols.GROUP_TARGETS:
            return list(self.handles)
        return [self.bound[to]]

    def fields(self, *, round_n: int = 1, rounds: int = 1) -> _Fields:
        said = [(h, self.replies[h]) for h in self.handles if self.replies.get(h)]
        return _Fields(
            ask=self.ask,
            reply=self.recent,
            replies="\n".join(f"- {h}: {p}" for h, p in said) or "(nothing yet)",
            handles=", ".join(self.handles),
            round=str(round_n),
            rounds=str(rounds),
        )


def bind_roles(protocol: Protocol, handles: list[str]) -> dict[str, str] | None:
    """Roles bound to ``handles`` in order, or ``None`` when there are too few."""
    if len(handles) < len(protocol.roles):
        return None
    return dict(zip(protocol.roles, handles, strict=False))


def stance_of_step(replies: list[tuple[str, str | None]]) -> str | None:
    """The stance a step took across everyone it asked.

    One reply's stance is its own. Across several, a single block is a
    block, everyone accepting is an accept, and anything else states none.
    ``"silent"`` when nobody answered at all.
    """
    if not replies:
        return None
    stances = [s for _h, s in replies]
    if all(s == "silent" for s in stances):
        return "silent"
    if any(s == "reject" for s in stances):
        return "reject"
    if all(s == "accept" for s in stances):
        return "accept"
    return None


class ConductorEngine:
    """Walk a protocol's steps over a thread, holding its floor as it goes."""

    def __init__(
        self,
        manager: RoomChannelManager,
        *,
        handle: str | None = None,
        step_timeout_s: float | None = None,
        poll_interval_s: float | None = None,
        max_steps: int | None = None,
    ) -> None:
        self._manager = manager
        self._handle = handle if handle is not None else settings.CONDUCTOR_HANDLE
        self._step_timeout_s = (
            step_timeout_s if step_timeout_s is not None else settings.CONDUCTOR_STEP_TIMEOUT_S
        )
        self._poll_interval_s = (
            poll_interval_s if poll_interval_s is not None else settings.CONDUCTOR_POLL_INTERVAL_S
        )
        self._max_steps = max_steps if max_steps is not None else settings.CONDUCTOR_MAX_STEPS
        # Threads with a run in flight: a re-summon into one is ignored while a
        # second thread in the same room runs its own.
        self._active: set[tuple[str, str]] = set()
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def handle(self) -> str:
        return self._handle

    # -- the summon seam --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: L9,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        """Run a protocol when a registered engine of kind ``conductor`` is
        summoned; else ignore."""
        if _registered_engine_kind(room, handle) != ENGINE_KIND:
            return
        if settings.ENGINE_RUNTIME == "host":
            logger.info("engine @%s summoned in %s but ENGINE_RUNTIME=host", handle, room)
            return
        from app.services.persister import envelope_sender

        sender = envelope_sender(envelope)
        if sender is not None and _norm(sender) in {_norm(self._handle), _norm(handle)}:
            return
        summoned_in = (envelope.header.message.episode if envelope.header.message else None) or ""
        in_thread = bool(summoned_in) and not l9.is_live_episode(room, summoned_in)
        episode = summoned_in if in_thread else l9.episode_urn(room, mint_episode_id())
        key = (room, episode)
        if key in self._active:
            logger.debug("conductor already running in %s; ignoring re-summon", episode)
            return
        drop = {_norm(handle), _norm(self._handle), *(_norm(h) for h in _NON_PARTICIPANTS)}
        named = [h for h in (co_summons or []) if _norm(h) not in drop]
        directive = _MENTION.sub(
            lambda m: "" if _norm(m.group(0)) == _norm(handle) else m.group(0), message_text
        )
        self._active.add(key)
        task = asyncio.create_task(
            self._run_and_release(room, handle, episode, summoned_in, directive, named, key)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(
        self,
        room: str,
        engine_handle: str,
        episode: str,
        summoned_in: str,
        directive: str,
        named: list[str],
        key: tuple[str, str],
    ) -> None:
        try:
            await self.run(
                room,
                engine_handle=engine_handle,
                episode=episode,
                summoned_in=summoned_in,
                directive=directive,
                named=named,
            )
        except Exception:
            logger.exception("conductor @%s failed in %s", engine_handle, episode)
        finally:
            self._active.discard(key)

    # -- the run --

    async def run(
        self,
        room: str,
        *,
        episode: str,
        directive: str,
        engine_handle: str | None = None,
        summoned_in: str = "",
        named: list[str] | None = None,
    ) -> str | None:
        """Run the protocol ``directive`` names over ``episode``; return the outcome.

        ``named`` are the handles the summon mentioned, bound to the protocol's
        roles in order; with none named, every other member of the room takes
        part. ``None`` when the run could not start — the reason is posted
        where the summon was made.
        """
        managed = self._manager.get(room)
        if managed is None or managed.persister is None:
            logger.info("conductor summoned for %s but no live channel", room)
            return None
        me = engine_handle or self._handle
        where = summoned_in or episode

        name, ask = split_directive(directive)
        protocol = protocols.load_protocol(room, name) if name else None
        if protocol is None:
            known = ", ".join(protocols.builtin_names())
            await self._say(
                managed,
                where,
                me,
                "I need a protocol to run: name it first, then who takes part, for "
                "example `gated proposer-handle guardian-handle: the question`. "
                f"Built in: {known}; a room adds its own under protocols/.",
            )
            return None
        drop = {_norm(me), *(_norm(h) for h in _NON_PARTICIPANTS)}
        handles = [h for h in (named or []) if _norm(h) not in drop] or [
            m for m in self._manager.members(room) if _norm(m) not in drop
        ]
        bound = bind_roles(protocol, handles)
        if bound is None or not handles:
            roles = ", ".join(protocol.roles) or "its steps"
            await self._say(
                managed,
                where,
                me,
                f"`{protocol.name}` needs {max(len(protocol.roles), 1)} member(s) for {roles} "
                f"and {len(handles)} were named. Summon me again with the handles in that order.",
            )
            return None

        run = Run(protocol=protocol, ask=ask, handles=handles, bound=bound, episode=episode)
        ep = l9_episode.EpisodeState(
            episode=episode,
            topic=l9.topic_urn(room),
            parent_room=room,
            short_id=mint_episode_id(),
            workspace_id=managed.workspace,
            mas_id="",
            agents=list(handles),
            engine_handle=me,
        )
        intent = l9.build_envelope(
            kind=Kind.intent,
            subkind="mission",
            episode=episode,
            sender=me,
            recipients=handles,
            topic=ep.topic,
            payload_type="utterance",
            payload_data={"content": f"run {protocol.name}: {ask}", "roles": bound},
        )
        ep.intent_id = intent.header.message.id if intent.header.message else ""
        ep.messages.append(l9.envelope_to_dict(intent))
        logger.info("conductor @%s runs %s in %s over %s", me, protocol.name, episode, handles)
        # The floor is the run's from the first instant, so a member the summon
        # woke cannot slip a reply in ahead of the first step.
        self._manager.hold_floor(room, episode, holder=me)
        try:
            outcome, why = await self._walk(managed, run, ep, me)
        finally:
            self._manager.release_floor(room, episode)
        await self._close(managed, run, ep, me, outcome, why)
        return outcome

    async def _walk(
        self, managed: ManagedRoomChannel, run: Run, ep: l9_episode.EpisodeState, me: str
    ) -> tuple[str, str]:
        """Follow the steps until an end step or the cap; ``(outcome, reason)``."""
        protocol = run.protocol
        cap = min(protocol.max_steps, self._max_steps)
        step = protocol.first
        while True:
            if step.end is not None:
                return step.end, f"reached `{step.id}`"
            if run.steps_taken >= cap:
                return "rejected", f"hit the step cap ({cap}) at `{step.id}`"
            run.steps_taken += 1
            stances = await self._take(managed, run, ep, me, step)
            step = protocol.step(step.edge(stance_of_step(stances)))

    async def _take(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: l9_episode.EpisodeState,
        me: str,
        step: Step,
    ) -> list[tuple[str, str | None]]:
        """Put one step to its targets; return each target's stance."""
        room = managed.room
        targets = run.targets(step)
        stances: list[tuple[str, str | None]] = []
        for round_n in range(1, step.rounds + 1):
            if step.wait == "none":
                self._manager.hold_floor(room, run.episode, holder=me)
                prompt = step.prompt.format_map(run.fields(round_n=round_n, rounds=step.rounds))
                for handle in targets:
                    await self._tell(managed, ep, me, run, step, handle, prompt)
                return []
            if step.to in ("all", "workers"):
                prompt = step.prompt.format_map(run.fields(round_n=round_n, rounds=step.rounds))
                self._manager.hold_floor(room, run.episode, holder=me, speakers=targets)
                stances = list(
                    await asyncio.gather(
                        *(self._turn(managed, ep, me, run, step, h, prompt) for h in targets)
                    )
                )
                continue
            # A role, or each member in turn: one speaker at a time, each seeing
            # what the ones before it said.
            stances = []
            for handle in targets:
                prompt = step.prompt.format_map(run.fields(round_n=round_n, rounds=step.rounds))
                self._manager.hold_floor(room, run.episode, holder=me, speakers=[handle])
                stances.append(await self._turn(managed, ep, me, run, step, handle, prompt))
        return stances

    async def _turn(
        self,
        managed: ManagedRoomChannel,
        ep: l9_episode.EpisodeState,
        me: str,
        run: Run,
        step: Step,
        handle: str,
        prompt: str,
    ) -> tuple[str, str | None]:
        """Ask ``handle`` one step; ``(handle, stance)`` with ``"silent"`` for no reply."""
        assert managed.persister is not None  # checked by run()
        episode = run.episode
        pending = _norm(handle)
        answered: list[TranscriptRecord] = []

        def is_reply(record: TranscriptRecord) -> bool:
            if record.kind != "exchange" or _norm(record.sender) != pending:
                return False
            if record_episode(record) != episode:
                return False
            payload = (record.content.get("l9") or {}).get("payload") or {}
            return payload.get("type") not in _NOT_A_REPLY

        def on_reply(record: TranscriptRecord) -> None:
            answered.append(record)
            env = record.content.get("l9")
            if isinstance(env, dict):
                ep.messages.append(env)

        prose = await turns.addressed_turn(
            managed,
            managed.persister,
            sender=me,
            handle=handle,
            episode=episode,
            topic=ep.topic,
            prompt=prompt,
            payload_data={"step": step.id, "protocol": run.protocol.name},
            is_reply=is_reply,
            timeout_s=self._step_timeout_s,
            poll_interval_s=self._poll_interval_s,
            on_tick=lambda env: ep.messages.append(l9.envelope_to_dict(env)),
            on_reply=on_reply,
        )
        if not answered:
            return handle, "silent"
        run.replies[handle] = prose
        run.recent = prose
        return handle, markers.stance_of(answered[-1].content)

    async def _tell(
        self,
        managed: ManagedRoomChannel,
        ep: l9_episode.EpisodeState,
        me: str,
        run: Run,
        step: Step,
        handle: str,
        prompt: str,
    ) -> None:
        """A fire-and-forget step: say it to one member and move on."""
        env = l9.build_envelope(
            kind=Kind.exchange,
            episode=run.episode,
            sender=me,
            recipients=[handle],
            topic=ep.topic,
            payload_type="tick",
            payload_data={"step": step.id, "protocol": run.protocol.name},
        )
        ep.messages.append(l9.envelope_to_dict(env))
        try:
            await managed.post(env, turns.neutralize_mentions(prompt))
        except Exception:
            logger.warning("conductor failed to post step %s to @%s", step.id, handle)

    async def _close(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: l9_episode.EpisodeState,
        me: str,
        outcome: str,
        why: str,
    ) -> None:
        """Commit the outcome onto the thread and write the record."""
        commit = l9.build_envelope(
            kind=Kind.commit,
            subkind=outcome,
            episode=run.episode,
            sender=me,
            recipients=run.handles,
            topic=ep.topic,
            payload_type="outcome",
            payload_data={
                "protocol": run.protocol.name,
                "steps": run.steps_taken,
                "reason": why,
                "roles": run.bound,
            },
        )
        ep.messages.append(l9.envelope_to_dict(commit))
        mark = "✓" if outcome == "resolved" else "✗"
        text = f"{mark} {run.protocol.name}: {outcome} after {run.steps_taken} step(s), {why}."
        try:
            await managed.post(commit, text, list_write=True)
        except Exception:
            logger.warning("conductor failed to post the outcome for %s", run.episode)
        l9_episode.write_episode_record(ep, outcome=outcome, metrics=None, tasks=None)

    async def _say(self, managed: ManagedRoomChannel, episode: str, sender: str, text: str) -> None:
        """Post a plain message from the engine into ``episode``."""
        env = l9.build_envelope(
            kind=Kind.exchange,
            episode=episode,
            sender=sender,
            topic=l9.topic_urn(managed.room),
            payload_type="message",
        )
        try:
            await managed.post(env, text, list_write=True)
        except Exception:
            logger.warning("conductor failed to post on room %s", managed.room)
