# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The conductor — the engine that runs an episode's interaction flow.

A fourth engine ``kind`` beside the aligner, the synthesizer and hello, and
the first with no model of its own. Summoned with the name of a flow
(:mod:`~app.services.protocols`) and the members to run it over, it opens an
**episode** of its own and walks the flow's steps in it: it holds the
episode's floor for whoever the step addresses, puts the step's prompt to
them through the same one-agent turn the aligner brokers with, reads the
stance their reply took, and follows the edge. Every judgment in a run — what
to propose, whether to block it — is made by the members it addresses. The
conductor only decides who speaks next: a model in the nodes, code on the
edges.

**The episode is the run, and it carries its flow.** The graph the conductor
walks and the trace of the steps it has taken are written onto the episode's
own record (``log/episodes/{id}.md``) as it goes, so an open run shows where
it stands and a finished one shows the shape of the interaction, not only
its messages. A summon from a task's thread nests the episode in that task
(the record says ``within``), and the thread gets one line when the run opens
and one when it ends; a summon from the room nests it in nothing. Tasks are
context or output, never the container the flow lives in.

What it shares with the other engines: dormant until a registered engine of
its kind is summoned, runs as that handle. What it does not share: it opens
no negotiation, so joining the room mid-run aborts nothing, and it never
calls Pi.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import yaml

from app.config import settings
from app.services import l9, l9_episode, markers, protocols, tasks, turns
from app.services import select as choosing
from app.services.agent_registry import norm_handle
from app.services.aligner import _NON_PARTICIPANTS, _registered_engine_kind
from app.services.episode_records import EPISODES_PREFIX
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

#: Summon words that ask for the catalogue rather than a run.
LIST_DIRECTIVES = frozenset({"list", "protocols", "flows", "help"})
#: ``show <flow>`` says one flow's spec, as YAML a room can save under
#: ``protocols/<flow>`` and edit. A built-in is never written there by itself.
SHOW_DIRECTIVES = frozenset({"show", "spec"})

#: Payloads that are never a member's answer to a step.
_NOT_A_REPLY = frozenset(
    {"presence", "keepalive", "tick", l9.PING_PAYLOAD_TYPE, l9.NOTICE_PAYLOAD_TYPE}
)

_MENTION = re.compile(r"@[\w.@-]+")
_LEADING_PUNCT = re.compile(r"^[\s:,;\u2014\u2013-]+")


def _norm(handle: str) -> str:
    return norm_handle(handle) or ""


def split_directive(text: str) -> tuple[str, str]:
    """``(flow name, the ask)`` from a summon's text.

    The first word that is not a mention names the flow; everything after
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
    """One run: what it is over, and what has been said in it."""

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
    #: The key of the row whose thread the run walks, for prompts to name it.
    task: str = ""
    #: What a step's replies were, by handle: the record each reply arrived
    #: as, for reading ratings and stances off. Reset at every step.
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The options suggested so far, lettered in cast order.
    options: list[choosing.Option] = field(default_factory=list)
    #: ``{member: {letter: 0-100}}``, the ratings given so far; a later rating
    #: of the same option replaces the earlier one.
    ratings: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Options before this index have been put to a rating round already.
    rated_upto: int = 0
    #: The latest select step's result, and how many picks the run has made.
    last_pick: dict[str, Any] | None = None
    picks: int = 0
    #: How many times each select step has sent it back for a fix.
    repairs: dict[str, int] = field(default_factory=dict)
    #: Who was least happy at the first sending back, and their rating then,
    #: so an agreement can say how far a fix moved them.
    first_short: tuple[str, int] | None = None

    def targets(self, step: Step) -> list[str]:
        to = step.to or ""
        if to == "workers":
            named = set(self.bound.values())
            return [h for h in self.handles if h not in named]
        if to in protocols.GROUP_TARGETS:
            return list(self.handles)
        if to == protocols.BOTTLENECK:
            least = (self.last_pick or {}).get("least_happy")
            return [least] if least else []
        return [self.bound[to]]

    def new_options(self) -> list[choosing.Option]:
        """Options no rating round has seen yet."""
        return self.options[self.rated_upto :]

    def fields(self, *, round_n: int = 1, rounds: int = 1) -> _Fields:
        said = [(h, self.replies[h]) for h in self.handles if self.replies.get(h)]
        fresh = self.new_options()
        return _Fields(
            ask=self.ask,
            reply=self.recent,
            replies="\n".join(f"- {h}: {p}" for h, p in said) or "(nothing yet)",
            handles=", ".join(self.handles),
            task=self.task or "this task",
            round=str(round_n),
            rounds=str(rounds),
            options="\n".join(f"{o.label}. {o.text}" for o in self.options) or "(none yet)",
            new_options="\n".join(f"{o.label}. {o.text}" for o in fresh) or "(none)",
            new_labels=" ".join(f"{o.label}=.." for o in fresh),
            scores=choosing.scorecard(self.last_pick) if self.last_pick else "",
            threshold=str((self.last_pick or {}).get("threshold", 70)),
            shortfall=self.shortfall(),
        )

    def shortfall(self) -> str:
        """What the least happy member is short by, said to them."""
        pick = self.last_pick or {}
        least = pick.get("least_happy")
        if not least:
            return ""
        rating = (pick.get("ratings") or {}).get(least)
        return f"You rated option {pick.get('pick')} {rating}; the bar is {pick.get('threshold')}"

    def flow(self) -> dict[str, Any]:
        """The flow as the episode record carries it: the graph plus the cast."""
        spec = protocols.spec_of(self.protocol)
        return {
            "name": self.protocol.name,
            **spec,
            "bound": dict(self.bound),
            "cast": list(self.handles),
            "ask": self.ask,
        }


#: The payload key every conductor post carries its structured line under. The
#: text of the post is what members read; this is what a surface draws instead,
#: so the thread shows a run's steps as a run rather than as walls of prompt.
LINE_KEY = "conductor"


def open_line(run: Run) -> dict[str, Any]:
    """The opening of a run: which flow, who plays what, and its steps."""
    named = set(run.bound.values())
    return {
        "event": "open",
        "protocol": run.protocol.name,
        "description": run.protocol.description,
        "roles": dict(run.bound),
        "members": [h for h in run.handles if h not in named],
        "steps": [
            {k: v for k, v in (("id", s.id), ("to", s.to), ("next", s.next), ("end", s.end)) if v}
            for s in run.protocol.steps
        ],
    }


def turn_line(run: Run, step: Step, handle: str, *, cap: int, round_n: int) -> dict[str, Any]:
    """One step put to one member."""
    line: dict[str, Any] = {
        "event": "turn",
        "protocol": run.protocol.name,
        "step": step.id,
        "to": handle,
        "turn": run.steps_taken,
        "cap": cap,
    }
    if step.rounds > 1:
        line |= {"round": round_n, "rounds": step.rounds}
    if step.wait == "none":
        line["tell"] = True
    return line


def edge_event(step: Step, stance: str | None, who: str) -> dict[str, Any]:
    """Which way a branching step went."""
    return {
        "event": "edge",
        "step": step.id,
        "who": who,
        "stance": stance,
        "next": step.edge(stance),
    }


def close_line(run: Run, outcome: str, why: str) -> dict[str, Any]:
    """How the run ended."""
    line: dict[str, Any] = {
        "event": "close",
        "protocol": run.protocol.name,
        "outcome": outcome,
        "steps": run.steps_taken,
        "reason": why,
    }
    if run.last_pick and run.last_pick.get("pick"):
        line |= {"pick": run.last_pick["pick"], "text": run.last_pick["text"]}
    return line


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
    """Open an episode, walk its flow, hold its floor as it goes."""

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
        # Threads a run was summoned from, with one in flight: a second summon
        # from the same thread is ignored until it ends, while another thread
        # (or the room) can start its own.
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
        """Open a run when a registered engine of kind ``conductor`` is
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
        thread = summoned_in or l9.live_episode_urn(room)
        key = (room, thread)
        if key in self._active:
            logger.debug("conductor already running in %s; ignoring re-summon", thread)
            return
        drop = {_norm(handle), _norm(self._handle), *(_norm(h) for h in _NON_PARTICIPANTS)}
        named = [h for h in (co_summons or []) if _norm(h) not in drop]
        directive = _MENTION.sub(
            lambda m: "" if _norm(m.group(0)) == _norm(handle) else m.group(0), message_text
        )
        # The thread's floor is the run's from this instant, before anything
        # else on the loop runs: a member the summon woke cannot slip a reply
        # in ahead of the first step, and a persona mentioned as a role is not
        # asked a question. The room itself never holds a floor.
        if not l9.is_live_episode(room, thread):
            self._manager.hold_floor(room, thread, holder=handle)
        self._active.add(key)
        task = asyncio.create_task(
            self._run_and_release(room, handle, thread, directive, named, key)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(
        self,
        room: str,
        engine_handle: str,
        thread: str,
        directive: str,
        named: list[str],
        key: tuple[str, str],
    ) -> None:
        try:
            await self.run(
                room,
                engine_handle=engine_handle,
                episode=thread,
                directive=directive,
                named=named,
            )
        except Exception:
            logger.exception("conductor @%s failed in %s", engine_handle, thread)
        finally:
            # A run that never started still took the floor at the summon.
            if not l9.is_live_episode(room, thread):
                self._manager.release_floor(room, thread)
            self._active.discard(key)

    # -- the run --

    async def run(
        self,
        room: str,
        *,
        directive: str,
        engine_handle: str | None = None,
        episode: str | None = None,
        named: list[str] | None = None,
    ) -> str | None:
        """Run the flow ``directive`` names inside ``episode``; return the outcome.

        ``episode`` is the thread the ask was made in — a task's thread, where
        the run walks, or the room, where only ``list`` and ``show`` are
        answered: a run needs a task, so it has a thread to hold the floor of
        and a row to belong to. ``named`` are the handles the summon mentioned,
        bound to the flow's roles in order; with none named, every other member
        of the room takes part. ``None`` when the run could not start.
        """
        managed = self._manager.get(room)
        if managed is None or managed.persister is None:
            logger.info("conductor summoned for %s but no live channel", room)
            return None
        me = engine_handle or self._handle
        thread = episode or l9.live_episode_urn(room)
        in_task = not l9.is_live_episode(room, thread)

        name, ask = split_directive(directive)
        if name in LIST_DIRECTIVES:
            await self._say(managed, thread, me, self._catalogue(room))
            return None
        if name in SHOW_DIRECTIVES:
            await self._say(managed, thread, me, self._spec(room, ask.split()[0] if ask else ""))
            return None
        protocol = protocols.load_protocol(room, name) if name else None
        if protocol is None:
            known = ", ".join(protocols.builtin_names())
            await self._say(
                managed,
                thread,
                me,
                "I need a flow to run: name it first, then who takes part, for "
                "example `gated proposer-handle guardian-handle: the question`. "
                f"Built in: {known}; a room adds its own under protocols/.",
            )
            return None
        if not in_task:
            await self._say(
                managed,
                thread,
                me,
                f"A run needs a task: summon me inside one, `board coordinate <row> conductor "
                f'"{protocol.name} …"`, so it has a thread to walk and a row it belongs to.',
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
                thread,
                me,
                f"`{protocol.name}` needs {max(len(protocol.roles), 1)} member(s) for {roles} "
                f"and {len(handles)} were named. Summon me again with the handles in that order.",
            )
            return None

        # The run walks in the task's own thread; its record is a nested
        # episode of its own — the same slice, with the flow and the trace on
        # it — so the task stays one row and one thread.
        row = tasks.row_of_episode(room, thread)
        run = Run(
            protocol=protocol,
            ask=ask,
            handles=handles,
            bound=bound,
            episode=thread,
            task=row[0] if row else "",
        )
        ep = l9_episode.EpisodeState(
            episode=thread,
            topic=l9.topic_urn(room),
            parent_room=room,
            short_id=mint_episode_id(),
            workspace_id=managed.workspace,
            mas_id="",
            agents=list(handles),
            engine_handle=me,
            flow=run.flow(),
            within=thread,
        )
        intent = l9.build_envelope(
            kind=Kind.intent,
            subkind="mission",
            episode=thread,
            sender=me,
            recipients=handles,
            topic=ep.topic,
            payload_type="utterance",
            payload_data={"content": f"run {protocol.name}: {ask}", "roles": bound},
        )
        ep.intent_id = intent.header.message.id if intent.header.message else ""
        ep.messages.append(l9.envelope_to_dict(intent))
        logger.info("conductor @%s runs %s in %s over %s", me, protocol.name, thread, handles)
        # The floor is the run's from the first instant. (The summon seam
        # already held it; a direct call takes it here.)
        self._manager.hold_floor(room, thread, holder=me)
        try:
            # The record exists from the opening, so the run can be read while
            # it is still walking.
            l9_episode.write_episode_record(ep, outcome="open", metrics=None, tasks=None)
            await self._say(managed, thread, me, self._opening(run), line=open_line(run))
            outcome, why = await self._walk(managed, run, ep, me)
        finally:
            self._manager.release_floor(room, thread)
        await self._close(managed, run, ep, me, outcome, why)
        return outcome

    def _spec(self, room: str, name: str) -> str:
        """One flow as the YAML a ``protocols/<name>`` memory carries."""
        protocol = protocols.load_protocol(room, name.lower()) if name else None
        if protocol is None:
            known = ", ".join(
                sorted(set(protocols.builtin_names()) | set(protocols.room_protocol_names(room)))
            )
            return f"I know no flow called `{name}`. I can show: {known}."
        body = yaml.safe_dump(
            protocols.spec_of(protocol), sort_keys=False, default_flow_style=False
        ).strip()
        origin = (
            "this room's" if name.lower() in protocols.room_protocol_names(room) else "built in"
        )
        return (
            f"`{protocol.name}` ({origin}). Save this as `protocols/{protocol.name}` to edit it:\n\n"
            f"```yaml\n{body}\n```"
        )

    def _catalogue(self, room: str) -> str:
        """Every flow this room can run, each with its steps."""
        blocks = []
        own = set(protocols.room_protocol_names(room))
        for name in sorted(own | set(protocols.builtin_names())):
            spec = protocols.load_protocol(room, name)
            if spec is None:
                continue
            origin = "this room's" if name in own else "built in"
            blocks.append(f"{protocols.describe(spec)}\n({origin})")
        return (
            "Flows I can run. Summon me with the name, the members in role order, "
            "then the question: `gated api-handle sec-handle: rotate the key`.\n\n"
            + "\n\n".join(blocks)
        )

    @staticmethod
    def _cast(run: Run) -> str:
        cast = ", ".join(f"{h} as {role}" for role, h in run.bound.items())
        others = [h for h in run.handles if h not in run.bound.values()]
        if others:
            cast = ", ".join(x for x in (cast, f"{', '.join(others)} as members") if x)
        return cast or ", ".join(run.handles)

    @classmethod
    def _opening(cls, run: Run) -> str:
        """The first line of a run: who plays what, and the graph about to be walked."""
        return f"Running {run.protocol.name} with {cls._cast(run)}.\n\n{protocols.describe(run.protocol)}"

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
            if step.kind == "select":
                # A pick asks nobody, so it costs no step; a graph that loops
                # through picks alone is still bounded.
                run.picks += 1
                if run.picks > cap + 1:
                    return "rejected", f"picked {run.picks - 1} times without asking anyone"
                nxt = await self._select(managed, run, ep, me, step)
                if nxt is None:
                    outcome = (run.last_pick or {}).get("outcome")
                    return "rejected", f"`{step.id}` came out {outcome} with no edge for it"
                step = protocol.step(nxt)
                continue
            if run.steps_taken >= cap:
                return "rejected", f"hit the step cap ({cap}) at `{step.id}`"
            run.steps_taken += 1
            stances = await self._take(managed, run, ep, me, step, cap)
            stance = stance_of_step(stances)
            nxt = step.edge(stance)
            ep.trace.append(
                {
                    "step": step.id,
                    "turn": run.steps_taken,
                    "asked": [h for h, _s in stances] or run.targets(step),
                    "stances": {h: s for h, s in stances},
                    "stance": stance,
                    "next": nxt,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            # The record moves with the run, so an open episode shows where it is.
            l9_episode.write_episode_record(ep, outcome="open", metrics=None, tasks=None)
            who = ", ".join(h for h, _s in stances) or (step.to or "")
            line = protocols.edge_line(step, stance, who)
            if line is not None:
                # A branch taken is the one thing a reader cannot infer from the
                # replies alone, so it is said in the episode.
                await self._say(managed, run.episode, me, line, line=edge_event(step, stance, who))
            step = protocol.step(nxt)

    async def _select(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: l9_episode.EpisodeState,
        me: str,
        step: Step,
    ) -> str | None:
        """Pick among the options by the ratings given; post the scorecard;
        return the next step's id, or ``None`` when no edge takes the outcome."""
        done = run.repairs.get(step.id, 0)
        record = choosing.pick(
            run.options,
            run.handles,
            run.ratings,
            step.threshold if step.threshold is not None else protocols.DEFAULT_THRESHOLD,
            repairs_done=done,
            max_repairs=step.max_repairs
            if step.max_repairs is not None
            else protocols.DEFAULT_MAX_REPAIRS,
        )
        outcome = record["outcome"]
        if outcome == "infeasible":
            run.repairs[step.id] = done + 1
            least = record["least_happy"]
            if run.first_short is None and least:
                run.first_short = (least, record["ratings"][least])
        run.last_pick = record
        edges = step.next if isinstance(step.next, dict) else {}
        nxt = edges.get(outcome) or edges.get("default")
        ep.trace.append(
            {
                "step": step.id,
                "turn": run.steps_taken,
                "select": {
                    k: record[k] for k in ("outcome", "pick", "lowest", "missing", "least_happy")
                },
                "next": nxt,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        l9_episode.write_episode_record(ep, outcome="open", metrics=None, tasks=None)
        await self._say(
            managed,
            run.episode,
            me,
            choosing.scorecard(record),
            line={"event": "select", "step": step.id, "next": nxt, "select": record},
        )
        return nxt

    async def _take(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: l9_episode.EpisodeState,
        me: str,
        step: Step,
        cap: int,
    ) -> list[tuple[str, str | None]]:
        """Put one step to its targets; return each target's stance.

        A step that collects adds what the replies carried to the run; one that
        requires something asks, once, whoever replied without it.
        """
        stances = await self._ask(managed, run, ep, me, step, cap)
        replied = set(run.answers)
        self._collect(run, step, list(run.answers))
        lacking = self._lacking(run, step, stances)
        if lacking and run.steps_taken < cap:
            stances = await self._reask(managed, run, ep, me, step, cap, lacking, stances)
        if step.collect == "scores":
            run.rated_upto = len(run.options)
        if step.needs == "stance":
            # Someone who wrote back but never marked a stance, even when asked
            # again, objected: a written objection is never read as consent.
            stances = [(h, "reject" if h in replied and s is None else s) for h, s in stances]
        return stances

    def _collect(self, run: Run, step: Step, answered: list[str]) -> None:
        """Add what the replies of ``answered`` carried: options in cast order
        (whatever order they arrived in), or ratings of the options on the table."""
        order = [h for h in run.handles if h in answered]
        if step.collect == "options":
            for handle in order:
                _found, prose = markers.parse_marker(run.replies.get(handle, ""))
                choosing.add_option(run.options, prose, handle)
        elif step.collect == "scores":
            labels = {o.label for o in run.options}
            for handle in order:
                given = markers.scores_of(run.answers[handle])
                kept = {k: v for k, v in given.items() if k in labels}
                if kept:
                    run.ratings.setdefault(handle, {}).update(kept)

    @staticmethod
    def _lacking(run: Run, step: Step, stances: list[tuple[str, str | None]]) -> list[str]:
        """Who replied without what the step requires. Silence is not lacking:
        a member who didn't answer isn't asked again."""
        if step.needs == "scores":
            wanted = {o.label for o in run.new_options()}
            return [
                h
                for h in run.handles
                if h in run.answers and not wanted <= set(run.ratings.get(h, {}))
            ]
        if step.needs == "stance":
            return [h for h, s in stances if s is None and h in run.answers]
        return []

    async def _reask(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: l9_episode.EpisodeState,
        me: str,
        step: Step,
        cap: int,
        lacking: list[str],
        stances: list[tuple[str, str | None]],
    ) -> list[tuple[str, str | None]]:
        """One more turn for just ``lacking``, at once, as its own step."""
        run.steps_taken += 1
        if step.needs == "scores":
            labels = " ".join(f"{o.label}=.." for o in run.new_options())
            ask = (
                "I couldn't read your ratings. End your reply with "
                f"[[mycelium: {labels}]], one number 0-100 per option."
            )
        else:
            ask = (
                "I couldn't tell whether you accept this. End your reply with "
                "[[mycelium: stance=accept]] or [[mycelium: stance=reject]]."
            )
        head = f"{run.protocol.name} · {step.id} (again) · turn {run.steps_taken} of {cap}"
        self._manager.hold_floor(managed.room, run.episode, holder=me, speakers=lacking)
        run.answers = {}
        again = dict(
            await asyncio.gather(
                *(
                    self._turn(
                        managed,
                        ep,
                        me,
                        run,
                        h,
                        f"{head} · {h}\n\n{ask}",
                        {
                            "step": step.id,
                            "protocol": run.protocol.name,
                            LINE_KEY: turn_line(run, step, h, cap=cap, round_n=1) | {"again": True},
                        },
                    )
                    for h in lacking
                )
            )
        )
        self._collect(run, step, list(run.answers))
        ep.trace.append(
            {
                "step": step.id,
                "turn": run.steps_taken,
                "again": True,
                "asked": lacking,
                "stances": again,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        # A re-asked member's answer is the one that counts; a silent one keeps
        # what it said the first time.
        return [(h, again[h] if again.get(h, "silent") != "silent" else s) for h, s in stances]

    async def _ask(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: l9_episode.EpisodeState,
        me: str,
        step: Step,
        cap: int,
    ) -> list[tuple[str, str | None]]:
        """Put one step to its targets; return each target's stance."""
        room = managed.room
        targets = run.targets(step)
        stances: list[tuple[str, str | None]] = []
        run.answers = {}

        def render(handle: str, round_n: int) -> str:
            # Every turn says which step of which flow it is, so the episode
            # reads as a run and not as a conversation that happened to occur.
            head = f"{run.protocol.name} · {step.id} · turn {run.steps_taken} of {cap} · {handle}"
            body = step.prompt.format_map(run.fields(round_n=round_n, rounds=step.rounds))
            return f"{head}\n\n{body}"

        def data(handle: str, round_n: int) -> dict[str, Any]:
            return {
                "step": step.id,
                "protocol": run.protocol.name,
                LINE_KEY: turn_line(run, step, handle, cap=cap, round_n=round_n),
            }

        for round_n in range(1, step.rounds + 1):
            if step.wait == "none":
                self._manager.hold_floor(room, run.episode, holder=me)
                for handle in targets:
                    await self._tell(
                        managed, ep, me, run, handle, render(handle, round_n), data(handle, round_n)
                    )
                return []
            if step.to in ("all", "workers"):
                self._manager.hold_floor(room, run.episode, holder=me, speakers=targets)
                stances = list(
                    await asyncio.gather(
                        *(
                            self._turn(
                                managed, ep, me, run, h, render(h, round_n), data(h, round_n)
                            )
                            for h in targets
                        )
                    )
                )
                continue
            # A role, or each member in turn: one speaker at a time, each seeing
            # what the ones before it said.
            stances = []
            for handle in targets:
                self._manager.hold_floor(room, run.episode, holder=me, speakers=[handle])
                stances.append(
                    await self._turn(
                        managed, ep, me, run, handle, render(handle, round_n), data(handle, round_n)
                    )
                )
        return stances

    async def _turn(
        self,
        managed: ManagedRoomChannel,
        ep: l9_episode.EpisodeState,
        me: str,
        run: Run,
        handle: str,
        prompt: str,
        data: dict[str, Any],
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
            # Posted as a message, not a tick: a turn is prose the room should
            # read in the thread, the way the aligner's questions are.
            payload_type="message",
            payload_data=data,
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
        run.answers[handle] = answered[-1].content
        return handle, markers.stance_of(answered[-1].content)

    async def _tell(
        self,
        managed: ManagedRoomChannel,
        ep: l9_episode.EpisodeState,
        me: str,
        run: Run,
        handle: str,
        prompt: str,
        data: dict[str, Any],
    ) -> None:
        """A fire-and-forget step: say it to one member and move on."""
        env = l9.build_envelope(
            kind=Kind.exchange,
            episode=run.episode,
            sender=me,
            recipients=[handle],
            topic=ep.topic,
            payload_type="message",
            payload_data=data,
        )
        ep.messages.append(l9.envelope_to_dict(env))
        try:
            await managed.post(env, turns.neutralize_mentions(prompt))
        except Exception:
            logger.warning("conductor failed to post step %s to @%s", data.get("step"), handle)

    async def _close(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: l9_episode.EpisodeState,
        me: str,
        outcome: str,
        why: str,
    ) -> None:
        """Commit the outcome onto the thread and write the run's record.

        A run that picked carries its last pick, and an agreement commits
        ``converged`` with the decision and the task it came from, so the
        compile seam files any follow-up work under that task.
        """
        pick = run.last_pick
        data: dict[str, Any] = {
            "protocol": run.protocol.name,
            "steps": run.steps_taken,
            "reason": why,
            "roles": run.bound,
            "record": f"{EPISODES_PREFIX}{ep.short_id}",
            LINE_KEY: close_line(run, outcome, why),
        }
        metrics = None
        if pick is not None:
            data["select"] = pick
            given: dict[str, int] = pick.get("ratings") or {}
            if given:
                metrics = {
                    "satisfaction": {h: r / 100 for h, r in given.items()},
                    "min_satisfaction": min(given.values()) / 100,
                }
                data["metrics"] = metrics
        if outcome == "converged" and pick is not None:
            data["assignments"] = {"decision": pick["text"]}
            if run.task:
                data["within"] = run.task
        commit = l9.build_envelope(
            kind=Kind.commit,
            subkind=outcome,
            episode=run.episode,
            sender=me,
            recipients=run.handles,
            topic=ep.topic,
            payload_type="outcome",
            payload_data=data,
        )
        ep.messages.append(l9.envelope_to_dict(commit))
        text = f"{self._result_line(run, outcome, why)} Record: {EPISODES_PREFIX}{ep.short_id}."
        try:
            await managed.post(commit, text, list_write=True)
        except Exception:
            logger.warning("conductor failed to post the outcome for %s", run.episode)
        l9_episode.write_episode_record(ep, outcome=outcome, metrics=metrics, tasks=None)
        from app.services import analytics as usage

        await asyncio.to_thread(usage.flow_completed, run.protocol.name, outcome, run.steps_taken)
        if pick is not None:
            # An agreement run is a negotiation too, so the negotiation count
            # keeps counting whichever mechanism ran it.
            await asyncio.to_thread(usage.negotiation_completed, outcome, run.picks)

    @staticmethod
    def _result_line(run: Run, outcome: str, why: str) -> str:
        """The one line a person reads to know how the run ended."""
        pick = run.last_pick
        if pick is None or not pick.get("pick"):
            mark = "✓" if outcome in protocols.SUCCESS else "✗"
            return f"{mark} {run.protocol.name}: {outcome} after {run.steps_taken} step(s), {why}."
        label, text = pick["pick"], pick["text"]
        if outcome == "converged":
            moved = ""
            if run.first_short is not None:
                who, before = run.first_short
                after = (pick.get("ratings") or {}).get(who)
                if after is not None:
                    moved = f" @{who} went from {before} to {after}."
            return f"✓ Everyone's on board: going with {label}: {text}.{moved}"
        return f"✗ Couldn't get everyone there. Best was {label}: {text}. {choosing.summary(pick)}"

    async def _say(
        self,
        managed: ManagedRoomChannel,
        episode: str,
        sender: str,
        text: str,
        *,
        line: dict[str, Any] | None = None,
    ) -> None:
        """Post a plain message from the engine into ``episode``, with its line when it has one."""
        env = l9.build_envelope(
            kind=Kind.exchange,
            episode=episode,
            sender=sender,
            topic=l9.topic_urn(managed.room),
            payload_type="message",
            payload_data={LINE_KEY: line} if line else None,
        )
        try:
            await managed.post(env, text, list_write=True)
        except Exception:
            logger.warning("conductor failed to post on room %s", managed.room)
