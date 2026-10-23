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

**What a run agrees outlives it, in memory, never on the board.** A flow
that locks (``accord``) saves the shared summary it assembled, and a
``concord`` that converges saves its decision, each as a ``context/`` memory
for the task (:mod:`~app.services.agreed`); the commit points at it. A later
run in the same task is shown what was saved (``{agreed}``). No conductor
run files board rows.

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
from app.services import (
    agreed,
    concord_messages,
    episode_state,
    markers,
    message_format,
    protocols,
    reply_shape,
    tasks,
    turns,
)
from app.services import frame as framing
from app.services import select as choosing
from app.services.agent_registry import norm_handle
from app.services.aligner import _NON_PARTICIPANTS, _registered_engine_kind
from app.services.episode_records import EPISODES_PREFIX
from app.services.message_models import Kind
from app.services.persister import record_episode
from app.services.tasks import mint_episode_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.services.message_models import MyceliumMessage
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
    {
        "presence",
        "keepalive",
        "tick",
        message_format.PING_PAYLOAD_TYPE,
        message_format.NOTICE_PAYLOAD_TYPE,
    }
)

#: How alike a fix and an option already on the table can be before the fix
#: counts as the same option (with the embedding model; without it, equal text).
REPEAT_SIMILARITY = 0.92

#: A handle named in a summon, loud, silent (``@~``) or interrupting (``@!``).
_MENTION = re.compile(r"@[~!]?[\w.@-]+")
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


@dataclass
class Settings:
    """What a summon sets for its run, beside the question: the bar (0-1), how
    many fixes, the two reference outcomes, and the key terms."""

    bar: float | None = None
    fixes: int | None = None
    bad: str = ""
    ideal: str = ""
    terms: list[str] = field(default_factory=list)
    #: What a candidate has to say, for CONCORD's ``candidate_schema``.
    schema: str = ""


#: The two ends a concord is measured between when the summon names none:
#: no agreement at all, and each member's own choice.
DEFAULT_BAD = "no agreement: nothing is decided and the task stays open"
DEFAULT_IDEAL = "your own pick: the option you'd choose if it were up to you alone"

_BAR = re.compile(r"\bbar\s*[=:]\s*(\d{1,3})\s*%?", re.IGNORECASE)
_FIXES = re.compile(r"\bfixes\s*[=:]\s*(\d{1,2})\b", re.IGNORECASE)
#: ``bad: …``, ``ideal: …``, ``terms: …`` and ``schema: …``, each running to
#: the next of them.
_LABELLED = re.compile(r"\b(bad|ideal|terms|schema)\s*:\s*", re.IGNORECASE)


def run_settings(ask: str) -> tuple[str, Settings]:
    """``(the question, what the summon set)`` from a summon's ask.

    ``bar=60`` (a percentage) and ``fixes=3`` can sit anywhere in it.
    ``bad: …``, ``ideal: …``, ``terms: a, b`` and ``schema: …`` run to the next
    of them or the end, so they go after the question: ``decide the renewal
    offer bad: we lose Acme ideal: Acme renews for three years at full price``.
    """
    found = Settings()
    if m := _BAR.search(ask):
        value = int(m.group(1))
        if 0 < value <= 100:
            found.bar = value / 100
        ask = ask[: m.start()] + ask[m.end() :]
    if m := _FIXES.search(ask):
        found.fixes = int(m.group(1))
        ask = ask[: m.start()] + ask[m.end() :]
    marks = list(_LABELLED.finditer(ask))
    if marks:
        for i, mark in enumerate(marks):
            stop = marks[i + 1].start() if i + 1 < len(marks) else len(ask)
            value = ask[mark.end() : stop].strip().rstrip(".,;")
            kind = mark.group(1).lower()
            if kind == "terms":
                found.terms = [t.strip() for t in re.split(r"[,;]", value) if t.strip()][:5]
            elif kind == "bad":
                found.bad = value
            elif kind == "schema":
                found.schema = value
            else:
                found.ideal = value
        ask = ask[: marks[0].start()]
    return re.sub(r"\s+", " ", ask).strip().rstrip(",;"), found


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
    #: Turns put to members so far, re-asks included: what a turn's "turn N of
    #: cap" counts.
    steps_taken: int = 0
    #: Every step the run walked, the ones that ask nobody included: what its
    #: close says, set when it closes. The thread's header counts the same
    #: steps (the record's trace), so the two never disagree.
    walked: int = 0
    #: The key of the row whose thread the run walks, for prompts to name it,
    #: and its title, for prompts to say it.
    task: str = ""
    title: str = ""
    #: What a step's replies were, by handle: the record each reply arrived
    #: as, for reading ratings and stances off. Reset at every step.
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The options suggested so far, lettered in cast order.
    options: list[choosing.Option] = field(default_factory=list)
    #: ``{member: {option: 0-100}}``, the ratings given so far; a later rating
    #: of the same option replaces the earlier one.
    ratings: dict[str, dict[str, float]] = field(default_factory=dict)
    #: ``{member: {option: why}}``, the reason each rating came with.
    reasons: dict[str, dict[str, str]] = field(default_factory=dict)
    #: What the summon set: the bar, the fixes, the reference outcomes, the terms.
    settings: Settings = field(default_factory=Settings)
    #: ``{member: (bad, ideal)}``, each member's ratings of the two reference outcomes.
    anchors: dict[str, tuple[float, float]] = field(default_factory=dict)
    #: The key terms of an accord run, from the summon or as members named them.
    key_terms: list[str] = field(default_factory=list)
    #: Members who were refused a fix that repeated an option, so it's once each.
    repeat_refused: set[str] = field(default_factory=set)
    #: Options before this index have been put to a rating round already.
    rated_upto: int = 0
    #: The latest select step's result, and how many picks the run has made.
    last_pick: dict[str, Any] | None = None
    picks: int = 0
    #: How many times each select step has sent it back for a fix.
    repairs: dict[str, int] = field(default_factory=dict)
    #: Who was least happy at the first sending back, and their objection then,
    #: so an agreement can say what the fixes answered.
    first_short: tuple[str, str] | None = None
    #: Who didn't answer the last step taken, for the close to name.
    quiet: list[str] = field(default_factory=list)
    #: The points, words and checks members labelled, merged as they arrive.
    frame: framing.Frame = field(default_factory=framing.Frame)
    #: How many new points the latest step that gathers pieces added.
    added: int = 0
    #: How many times each tally step has run, and how many steps that ask
    #: nobody the run has taken (a graph that loops through them alone is
    #: still bounded).
    tallies: dict[str, int] = field(default_factory=dict)
    computed: int = 0
    #: The members the latest tally of words found using one in different senses.
    contested: list[str] = field(default_factory=list)
    terms_shown: str = ""
    #: The similarity points and meanings fold by, or ``None`` for equal text only.
    similar: framing.Similar | None = None
    #: What the team agreed earlier in this task, for prompts to carry.
    agreed: str = ""
    #: The assembled shared summary, when a lock made one.
    made: dict[str, Any] | None = None
    #: Where the run's result was saved; ``saving`` is set once there was
    #: something to save, so a failed write reads differently from none.
    saved_to: str | None = None
    saving: bool = False
    #: The step being asked now, whether this asking is a re-ask, and the
    #: members whose reply it waits on: what a reply recorded in the thread is
    #: read against (:meth:`ConductorEngine._reader`).
    asking: Step | None = None
    again: bool = False
    waiting: set[str] = field(default_factory=set)
    #: ``{member: {option}}``: ratings a member still hadn't given when asked
    #: again (CONCORD's MISSING). While any stands, nothing is agreed.
    unrated: dict[str, set[str]] = field(default_factory=dict)

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
        if to == protocols.CONTESTED:
            return list(self.contested)
        return [self.bound[to]]

    def new_options(self) -> list[choosing.Option]:
        """Options no rating round has seen yet."""
        return self.options[self.rated_upto :]

    def owed(self, handle: str) -> list[str]:
        """The options of this rating round ``handle`` hasn't scored with its
        reasoning yet."""
        given, why = self.ratings.get(handle, {}), self.reasons.get(handle, {})
        return [o.label for o in self.new_options() if o.label not in given or not why.get(o.label)]

    def bar(self) -> float:
        """The bar this run holds every member to, 0-1: the summon's, else the
        flow's select step's, else the default. Fixed for the run."""
        if self.settings.bar is not None:
            return self.settings.bar
        select = next((s for s in self.protocol.steps if s.kind == "select"), None)
        if select is not None and select.threshold is not None:
            return select.threshold
        return protocols.DEFAULT_THRESHOLD

    def fixes(self, step: Step) -> int:
        """How many fixes a select step may send for: the summon's, else its own."""
        if self.settings.fixes is not None:
            return self.settings.fixes
        return step.max_repairs if step.max_repairs is not None else protocols.DEFAULT_MAX_REPAIRS

    def bar_said(self) -> str:
        """The bar in terms of the two reference outcomes, never as a bare number."""
        if self.settings.bad in ("", DEFAULT_BAD) and self.settings.ideal in ("", DEFAULT_IDEAL):
            return (
                f"The bar: the option picked has to be at least {round(self.bar() * 100)}% of the "
                "way from no agreement to each member's own pick, for every member."
            )
        bad = self.settings.bad or "the bad outcome"
        ideal = self.settings.ideal or "the ideal one"
        return (
            f"The bar: the option picked has to be at least {round(self.bar() * 100)}% of the "
            f"way from *{bad}* to *{ideal}* for every member."
        )

    def _listed(self, options: list[choosing.Option]) -> str:
        """Options as raters read them: each with why its proposers proposed it."""
        lines = []
        for o in options:
            lines.append(f"{o.label}. {o.text}")
            lines += [f"   why ({h}): {w}" for h, w in o.why.items() if w]
        return "\n".join(lines)

    def objections(self) -> str:
        """What the members short of the bar said about the pick, in their words."""
        pick = self.last_pick or {}
        label = pick.get("pick")
        why = (pick.get("reasons") or {}).get(label, {}) if label else {}
        lines = [
            f"- {s['member']}: {s.get('why') or 'gave no reason'}" for s in pick.get("short") or []
        ]
        others = [
            h
            for h in self.handles
            if h in why and h not in {s["member"] for s in pick.get("short") or []}
        ]
        lines += [f"- {h} (meets the bar): {why[h]}" for h in others]
        return "\n".join(lines) or "- (no reasons given)"

    def fields(self, *, round_n: int = 1, rounds: int = 1) -> _Fields:
        said = [(h, self.replies[h]) for h in self.handles if self.replies.get(h)]
        fresh = self.new_options()
        pick = self.last_pick or {}
        return _Fields(
            ask=self.ask,
            reply=self.recent,
            replies="\n".join(f"- {h}: {p}" for h, p in said) or "(nothing yet)",
            handles=", ".join(self.handles),
            task=self.task or "this task",
            # The row's title, for prompts a person or a model reads: a key like
            # work/decide-the-renewal-offer-for-acme reads as a path, not a task.
            title=self.title or self.task or "this task",
            option_labels=" ".join(f"{o.label}=.." for o in self.options),
            round=str(round_n),
            rounds=str(rounds),
            options=self._listed(self.options) or "(none yet)",
            new_options=self._listed(fresh) or "(none)",
            new_labels=" ".join(f"{o.label}=.." for o in fresh),
            # Each line carries the option's name, so a reply reads as what it
            # rates, not as a bare letter.
            rating_lines=_rating_lines(self.options, self.options),
            new_rating_lines=_rating_lines(fresh, self.options),
            scores=choosing.scorecard(self.last_pick) if self.last_pick else "",
            standing="\n".join(f"- {v}" for v in choosing.views(pick, pick["pick"]))
            if pick.get("pick")
            else "",
            objections=self.objections(),
            bad=self.settings.bad or "the bad outcome",
            ideal=self.settings.ideal or "the ideal outcome",
            bar=str(round(self.bar() * 100)),
            bar_said=self.bar_said(),
            key_terms=", ".join(self.key_terms) or "(none named)",
            term_lines="\n".join(f"{t}: <what you mean, with units>" for t in self.key_terms)
            or "term <word>: <what you mean, with units>",
            # The best option so far in full: a fix revises it, so it has to
            # see what earlier fixes put in.
            pick=(
                f"{self.last_pick['pick']}. {self.last_pick['text']}"
                if self.last_pick and self.last_pick.get("pick")
                else ""
            ),
            threshold=str(round(self.bar() * 100)),
            shortfall=self.shortfall(),
            frame=framing.show_points(self.frame, self.handles),
            # Grouping meanings can call the embedding model, so the words are
            # shown as the latest tally of them grouped them, off the loop.
            terms=self.terms_shown or "(no words defined yet)",
            checks=framing.show_checks(self.frame),
            agreed=self.agreed,
            # CONCORD's messages, as its specification writes them.
            concord_anchor=concord_messages.anchor(
                self.bar(),
                self.settings.bad or DEFAULT_BAD,
                self.settings.ideal or DEFAULT_IDEAL,
            ),
            concord_seed=concord_messages.seed(self.candidate_schema(), self.bar(), self.context()),
            concord_score=concord_messages.score(
                self.context(), [self.candidate(o) for o in fresh or self.options]
            ),
            concord_repair=self.concord_repair(),
        )

    # -- CONCORD's messages --

    def context(self) -> str:
        """The problem statement CONCORD's messages carry: the task and the ask,
        and what the team agreed earlier in it."""
        said = f"{self.title or self.task or 'this task'}: {self.ask}".rstrip(": ")
        return f"{self.agreed.strip()}\n\n{said}" if self.agreed.strip() else said

    def candidate_schema(self) -> str:
        return self.settings.schema or (
            f"One option for {self.title or self.task or 'this task'}: what to do, "
            "in one or two sentences."
        )

    @staticmethod
    def candidate(option: choosing.Option) -> concord_messages.Candidate:
        rationale = " ".join(w for w in option.why.values() if w)
        return concord_messages.Candidate(id=option.label, text=option.text, rationale=rationale)

    def scored(self, label: str) -> list[concord_messages.Scored]:
        """Every member's normalized score of one option, with its reasoning."""
        out = []
        for h in self.handles:
            raw = self.ratings.get(h, {}).get(label)
            at = None if raw is None else choosing.placed(raw, self.anchors.get(h))
            out.append(concord_messages.Scored(h, at, self.reasons.get(h, {}).get(label, "")))
        return out

    def concord_repair(self) -> str:
        pick = self.last_pick or {}
        least = pick.get("least_happy")
        incumbent = next((o for o in self.options if o.label == pick.get("pick")), None)
        if incumbent is None or not least:
            return ""
        mine = next((s.score for s in self.scored(incumbent.label) if s.agent == least), None)
        return concord_messages.repair(
            self.bar(),
            self.candidate_schema(),
            self.context(),
            self.candidate(incumbent),
            mine or 0.0,
            self.scored(incumbent.label),
        )

    def shortfall(self) -> str:
        """Where the least happy member stands on the pick, said to them in words."""
        pick = self.last_pick or {}
        least = pick.get("least_happy")
        if not least:
            return ""
        at = (pick.get("standing") or {}).get(least)
        why = ((pick.get("reasons") or {}).get(pick.get("pick"), {}) or {}).get(least, "")
        said = choosing.verdict(at, self.bar())
        because = f", because {choosing.mid_sentence(why)}" if why else ""
        return (
            f"For you, {choosing.pick_named(pick)} is "
            f"{said}{because}. You're the one furthest from the bar."
        )

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
        "steps": run.walked,
        "reason": why,
    }
    if run.last_pick and run.last_pick.get("pick"):
        line |= {"pick": run.last_pick["pick"], "text": run.last_pick["text"]}
    if (commit := concord_commit(run, outcome)) is not None:
        line["commit"] = commit
    if run.saving:
        line["memory"] = run.saved_to
    return line


#: How a CONCORD run's ends read in its commit.
_COMMIT_OUTCOMES = {"converged": "SUCCESS", "resolved": "BEST_EFFORT"}


def speaks_concord(run: Run) -> bool:
    """Whether the run sends CONCORD's own messages (its steps name the spec's
    reply schemas), so it ends with CONCORD's commit."""
    return any((s.reply or "").startswith("concord-") for s in run.protocol.steps)


def concord_commit(run: Run, outcome: str) -> dict[str, Any] | None:
    """A CONCORD run's commit, as its specification names the fields: how it
    ended, the winning candidate, each member's normalized score for it (null
    for none), who is short of the bar and by how much, and who gave no score.
    ``None`` for any other run, or one that picked nothing."""
    pick = run.last_pick or {}
    label = pick.get("pick")
    if not speaks_concord(run) or not label or outcome not in _COMMIT_OUTCOMES:
        return None
    bar = run.bar()
    scores = {s.agent: s.score for s in run.scored(label)}
    return {
        "outcome": _COMMIT_OUTCOMES[outcome],
        "winning_candidate_id": label,
        "winning_candidate": pick.get("text", ""),
        "final_scores": {h: None if v is None else round(v, 4) for h, v in scores.items()},
        "shortfall": [
            {"agent": h, "score": round(v, 4), "short_by": round(bar - v, 4)}
            for h, v in scores.items()
            if v is not None and v < bar - choosing.TOL
        ],
        "unknown": [h for h, v in scores.items() if v is None],
        "satisfaction_threshold": bar,
        "repairs": sum(run.repairs.values()),
    }


def bind_roles(protocol: Protocol, handles: list[str]) -> dict[str, str] | None:
    """Roles bound to ``handles`` in order, or ``None`` when there are too few."""
    if len(handles) < len(protocol.roles):
        return None
    return dict(zip(protocol.roles, handles, strict=False))


def _rating_lines(options: list[choosing.Option], every: list[choosing.Option]) -> str:
    """The lines a member fills in to rate ``options``, each naming its option
    by a name no other option in ``every`` (the run's options) shares."""
    names = choosing.option_names([(o.label, o.text) for o in every])
    return "\n".join(f"{choosing.named(o.label, o.text, names)}: <0-100> - <why>" for o in options)


def _sentence(text: str) -> str:
    """``text`` ending in exactly one full stop, however it ended before."""
    return text.rstrip().rstrip(".") + "."


def _counted(numbers: dict[str, Any]) -> str:
    """A shared summary's size, as a person reads it."""
    parts = [
        f"{numbers['points']} point(s)",
        f"{numbers['shared']} stated by more than one person",
    ]
    if numbers["contested"]:
        parts.append(f"{numbers['contested']} word(s) used in different senses")
    if numbers["checks"]:
        parts.append(f"{numbers['checks']} check(s)")
    return ", ".join(parts) + "."


def _saved(run: Run, what: str) -> str:
    """Where a run's result went, or that it could not be saved."""
    if not run.saving:
        return ""
    if run.saved_to:
        return f" The {what} is saved as {run.saved_to}."
    return f" The {what} could not be saved."


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
        #: Called with ``(room, thread, outcome)`` after every step a run takes
        #: (``outcome`` None) and once when it closes, for anything that follows
        #: a run as it goes. It must return at once; a failure is logged.
        self.on_step: Callable[[str, str, str | None], None] | None = None
        #: Makes the similarity a run folds points and meanings by; ``None``
        #: from it means equal text only. Tests put their own in.
        self.similarity: Callable[[], framing.Similar | None] = framing.embedding_similarity

    def _stepped(self, room: str, thread: str, outcome: str | None) -> None:
        if self.on_step is None:
            return
        try:
            self.on_step(room, thread, outcome)
        except Exception:
            logger.exception("conductor step hook failed in %s", thread)

    @property
    def handle(self) -> str:
        return self._handle

    # -- the summon seam --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: MyceliumMessage,
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
        from app.services.persister import envelope_sender, parse_named

        sender = envelope_sender(envelope)
        if sender is not None and _norm(sender) in {_norm(self._handle), _norm(handle)}:
            return
        summoned_in = (envelope.header.message.episode if envelope.header.message else None) or ""
        thread = summoned_in or message_format.live_episode_urn(room)
        key = (room, thread)
        if key in self._active:
            logger.debug("conductor already running in %s; ignoring re-summon", thread)
            return
        drop = {_norm(handle), _norm(self._handle), *(_norm(h) for h in _NON_PARTICIPANTS)}
        # The members bound to roles are every handle the summon names, however
        # it names them: ``@~a`` binds a role without waking anyone, ``@a``
        # binds it and wakes them now, by the ordinary rule (``asks.py``).
        named = [h for h in parse_named(message_text) if _norm(h) not in drop]
        directive = _MENTION.sub(
            lambda m: "" if _norm(m.group(0).lstrip("@~!")) == _norm(handle) else m.group(0),
            message_text,
        )
        # The thread's floor is the run's from this instant, before anything
        # else on the loop runs: a member the summon woke cannot slip a reply
        # in ahead of the first step, and a persona mentioned as a role is not
        # asked a question. The room itself never holds a floor.
        if not message_format.is_live_episode(room, thread):
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
            if not message_format.is_live_episode(room, thread):
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
        thread = episode or message_format.live_episode_urn(room)
        in_task = not message_format.is_live_episode(room, thread)

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
        ask, set_by_summon = run_settings(ask)
        run = Run(
            protocol=protocol,
            ask=ask,
            handles=handles,
            bound=bound,
            episode=thread,
            task=row[0] if row else "",
            title=row[1] if row else "",
            similar=self.similarity(),
            settings=set_by_summon,
            key_terms=list(set_by_summon.terms),
        )
        # The two ends any agreement is measured between: no agreement at all,
        # and each member's own choice. They need nobody to write them; a
        # summon's `bad:` / `ideal:` names others in their place.
        run.settings.bad = run.settings.bad or DEFAULT_BAD
        run.settings.ideal = run.settings.ideal or DEFAULT_IDEAL
        if not run.similar:
            run.frame.similarity = False
        # What the team agreed earlier in this task, so a later flow builds on it.
        run.agreed = await asyncio.to_thread(agreed.for_prompt, room, run.task)
        ep = episode_state.EpisodeState(
            episode=thread,
            topic=message_format.topic_urn(room),
            parent_room=room,
            short_id=mint_episode_id(),
            workspace_id=managed.workspace,
            mas_id="",
            agents=list(handles),
            engine_handle=me,
            flow=run.flow(),
            within=thread,
        )
        intent = message_format.build_envelope(
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
        ep.messages.append(message_format.envelope_to_dict(intent))
        logger.info("conductor @%s runs %s in %s over %s", me, protocol.name, thread, handles)
        # The floor is the run's from the first instant. (The summon seam
        # already held it; a direct call takes it here.)
        self._manager.hold_floor(room, thread, holder=me)
        # Every reply recorded in the thread while the run walks is read against
        # the step waiting on it, and what was read goes on the message.
        self._manager.read_replies(room, thread, self._reader(run))
        try:
            # The record exists from the opening, so the run can be read while
            # it is still walking.
            episode_state.write_episode_record(ep, outcome="open", metrics=None, tasks=None)
            await self._say(managed, thread, me, self._opening(run), line=open_line(run))
            outcome, why = await self._walk(managed, run, ep, me)
        finally:
            self._manager.read_replies(room, thread, None)
            self._manager.release_floor(room, thread)
        await self._close(managed, run, ep, me, outcome, why)
        return outcome

    @classmethod
    def _reader(cls, run: Run) -> Callable[[str, dict[str, Any]], dict[str, Any] | None]:
        """What reads a member's reply to the step being asked, as it's recorded:
        ``None`` for anything else in the thread (the conductor's own posts, a
        member nobody is waiting on, a step that names no reply schema)."""

        def read(sender: str, content: dict[str, Any]) -> dict[str, Any] | None:
            step = run.asking
            who = _norm(sender)
            if step is None or step.reply is None or who not in run.waiting:
                return None
            payload = (content.get("l9") or {}).get("payload") or {}
            if payload.get("type") in _NOT_A_REPLY:
                return None
            handle = next((h for h in run.handles if _norm(h) == who), sender)
            reply = reply_shape.read(
                step.reply,
                content,
                candidates=run.owed(handle),
                anchor=run.anchors.get(handle),
            )
            reply["step"] = step.id
            if step.collect == "options" and reply["parsed"]:
                reply["value"]["candidate_id"] = cls.candidate_id(run, step, handle)
            if step.to == protocols.BOTTLENECK:
                reply["phase"] = "REPAIR"
            if run.again:
                reply["again"] = True
            return reply

        return read

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
        """The first line of a run: who plays what, what it holds them to, and
        the graph about to be walked.

        A run that picks says its bar here, before anyone rates, in terms of
        the two reference outcomes, and how many fixes it allows; a run that
        fixes key terms names them, or says the members will."""
        said = [f"Running {run.protocol.name} with {cls._cast(run)}."]
        select = next((s for s in run.protocol.steps if s.kind == "select"), None)
        if select is not None:
            said.append(run.bar_said())
            default = run.settings.bar is None and select.threshold == protocols.DEFAULT_THRESHOLD
            if default:
                said.append(
                    "That's the default bar; `bar=NN` in the summon sets another. It stays "
                    "the same for the whole run."
                )
            said.append(
                f"Up to {run.fixes(select)} fixes; then the best option found stands, saying "
                "who is still short and why."
            )
        if any(s.collect == "keywords" for s in run.protocol.steps):
            if run.key_terms:
                said.append(f"The key terms: {', '.join(run.key_terms)}.")
            else:
                said.append("The members will name the key terms first.")
        return " ".join(said) + f"\n\n{protocols.describe(run.protocol)}"

    async def _walk(
        self, managed: ManagedRoomChannel, run: Run, ep: episode_state.EpisodeState, me: str
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
            if step.kind in ("tally", "lock"):
                # Like a pick: code reads the run and asks nobody, so it costs
                # no step, and a graph that loops through these alone is bounded.
                run.computed += 1
                if run.computed > 2 * cap + 2:
                    return "rejected", f"ran {step.kind} steps {run.computed - 1} times"
                if step.kind == "tally":
                    came, nxt = await self._tally(managed, run, ep, me, step)
                else:
                    came, nxt = await self._lock(managed, run, ep, me, step)
                if nxt is None:
                    return "rejected", f"`{step.id}` came out {came} with no edge for it"
                step = protocol.step(nxt)
                continue
            if step.needs == "scores" and run.options and not run.new_options():
                # A fix that added nothing (the fixer was silent, or suggested an
                # option already on the table) leaves nothing new to rate: go on
                # without asking anyone to rate "(none)".
                ep.trace.append(
                    {
                        "step": step.id,
                        "turn": run.steps_taken,
                        "skipped": "nothing new to rate",
                        "next": step.edge(None),
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
                step = protocol.step(step.edge(None))
                continue
            if step.collect == "keywords" and run.key_terms:
                # The summon named the key terms, so nobody is asked for them.
                ep.trace.append(
                    {
                        "step": step.id,
                        "turn": run.steps_taken,
                        "skipped": "the summon named the key terms",
                        "next": step.edge(None),
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
                step = protocol.step(step.edge(None))
                continue
            if run.steps_taken >= cap:
                return "rejected", f"hit the step cap ({cap}) at `{step.id}`"
            run.steps_taken += 1
            stances = await self._take(managed, run, ep, me, step, cap)
            run.quiet = [h for h, s in stances if s == "silent"]
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
            episode_state.write_episode_record(ep, outcome="open", metrics=None, tasks=None)
            who = ", ".join(h for h, _s in stances) or (step.to or "")
            line = protocols.edge_line(step, stance, who)
            if line is not None:
                # A branch taken is the one thing a reader cannot infer from the
                # replies alone, so it is said in the episode.
                await self._say(managed, run.episode, me, line, line=edge_event(step, stance, who))
            self._stepped(managed.room, run.episode, None)
            step = protocol.step(nxt)

    async def _select(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: episode_state.EpisodeState,
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
            run.bar(),
            repairs_done=done,
            max_repairs=run.fixes(step),
            anchors=run.anchors,
            reasons=run.reasons,
            incumbent=(run.last_pick or {}).get("pick"),
            eps=step.eps or 0.0,
            unrated=run.unrated,
        )
        if not run.options:
            record["outcome"] = "nothing"
        outcome = record["outcome"]
        if outcome == "infeasible":
            run.repairs[step.id] = done + 1
            least = record["least_happy"]
            if run.first_short is None and least:
                why = (record.get("reasons") or {}).get(record["pick"], {}).get(least, "")
                run.first_short = (least, why)
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
        episode_state.write_episode_record(ep, outcome="open", metrics=None, tasks=None)
        await self._say(
            managed,
            run.episode,
            me,
            choosing.scorecard(record),
            line={"event": "select", "step": step.id, "next": nxt, "select": record},
        )
        return nxt

    @staticmethod
    def _edge(step: Step, came: str) -> str | None:
        if isinstance(step.next, str):
            return step.next
        edges = step.next or {}
        return edges.get(came) or edges.get("default")

    async def _tally(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: episode_state.EpisodeState,
        me: str,
        step: Step,
    ) -> tuple[str, str | None]:
        """Read the frame and say which way it went: ``(how it came out, next step)``.

        Of points: the last round added some (go round again), added none, or
        nobody has given any. Of words: some are used in different senses (ask
        those members, once), or none are. A tally that has run its
        ``max_rounds`` settles either way, and what was still moving is flagged.
        """
        n = run.tallies[step.id] = run.tallies.get(step.id, 0) + 1
        most = step.max_rounds or protocols.DEFAULT_MAX_ROUNDS[step.of or "points"]
        frame = run.frame
        report: dict[str, Any] = {"of": step.of, "round": n, "max_rounds": most}
        if step.of == "terms":
            words = await asyncio.to_thread(framing.contested, frame, run.similar)
            run.terms_shown = await asyncio.to_thread(framing.show_terms, frame, run.similar)
            again = bool(words) and n < most
            came = "contested" if again else "clear"
            run.contested = (
                await asyncio.to_thread(framing.contested_members, frame, run.handles, run.similar)
                if again
                else []
            )
            shown = [frame.terms[w][0] for w in words]
            report |= {
                "words": len(frame.terms),
                "contested": shown,
                "asked": list(run.contested),
            }
            if again:
                said = (
                    f"Words used in different senses: {', '.join(shown)}. Asking "
                    f"{', '.join(run.contested)} to say again what they mean."
                )
            elif words:
                said = (
                    f"Still used in different senses: {', '.join(shown)}. The meanings "
                    "are kept side by side in the shared summary."
                )
            else:
                said = (
                    f"{len(frame.terms)} word(s) defined, none used in different senses."
                    if frame.terms
                    else "Nobody defined a word."
                )
        else:
            total = len(frame.points)
            if not total:
                came = "empty"
            elif run.added and n < most:
                came = "grew"
            else:
                came = "settled"
                if run.added:
                    frame.capped = True
            report |= {"added": run.added, "points": total, "capped": frame.capped}
            if came == "empty":
                said = "Nobody gave any points."
            elif came == "grew":
                said = f"{run.added} new point(s), {total} in all so far."
            elif frame.capped:
                said = (
                    f"Points were still being added after {n} rounds; going on with the "
                    f"{total} there are."
                )
            else:
                said = f"Nobody added anything new; {total} points in all."
            if total:
                said += f"\n\n{framing.show_points(frame, run.handles)}"
        nxt = self._edge(step, came)
        report["outcome"] = came
        ep.trace.append(
            {
                "step": step.id,
                "turn": run.steps_taken,
                "tally": report,
                "next": nxt,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        episode_state.write_episode_record(ep, outcome="open", metrics=None, tasks=None)
        await self._say(
            managed,
            run.episode,
            me,
            said,
            line={"event": "tally", "step": step.id, "next": nxt, "tally": report},
        )
        return came, nxt

    async def _lock(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: episode_state.EpisodeState,
        me: str,
        step: Step,
    ) -> tuple[str, str | None]:
        """Assemble the shared summary from what the run gathered and save it to
        the room's memory: ``(how it came out, next step)``.

        Assembly, not a vote: everything flagged is recorded, and a member who
        disagrees with the result says so in the thread. Nothing to assemble
        (no points at all) comes out ``empty``. A failed save leaves the outcome
        as it is and says so.
        """
        frame = run.frame
        framing.known_covers(frame)
        made = await asyncio.to_thread(
            framing.contract,
            frame,
            cast=run.handles,
            ask=run.ask,
            task=run.task,
            title=run.title,
            similar=run.similar,
        )
        if not made["points"]:
            came, key, saved = "empty", None, False
        else:
            came = "locked"
            run.made = made
            run.saving = True
            key = agreed.summary_key(run.task or ep.short_id)
            saved = await agreed.save(
                managed.room,
                key,
                body=framing.render(made),
                meta={
                    agreed.CONTRACT_META: made,
                    "flow": run.protocol.name,
                    "record": f"{EPISODES_PREFIX}{ep.short_id}",
                },
                task=run.task,
                by=me,
                tags=["shared-summary"],
            )
            run.saved_to = key if saved else None
            ep.memory = run.saved_to
        nxt = self._edge(step, came)
        numbers = framing.counts(made)
        report = {"outcome": came, "memory": run.saved_to, "saved": saved, **numbers}
        ep.trace.append(
            {
                "step": step.id,
                "turn": run.steps_taken,
                "lock": report,
                "next": nxt,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        episode_state.write_episode_record(ep, outcome="open", metrics=None, tasks=None)
        if came == "empty":
            said = "There is nothing to put in a shared summary: nobody gave any points."
        else:
            items = [f["text"] for f in made["flags"]]
            listed = "\n".join(f"- {t}" for t in items) or "- None."
            where = (
                f"Saved as [[{key}]]. Later work in this task is held to it; a line "
                "starting `conflict:` in this thread adds to its open items."
                if saved
                else "The shared summary could not be saved; it is in this thread."
            )
            said = f"The shared summary: {_counted(numbers)}\n\nOpen items:\n{listed}\n\n{where}"
        await self._say(
            managed,
            run.episode,
            me,
            said,
            line={"event": "lock", "step": step.id, "next": nxt, "lock": report},
        )
        return came, nxt

    async def _save_decision(
        self, managed: ManagedRoomChannel, run: Run, ep: episode_state.EpisodeState, me: str
    ) -> None:
        """Save the option the run ended on to the room's memory, the way a
        shared summary is saved, so the work that follows can read it.

        It leads with reasons: the option, how each member sees it and why, and
        for a best found rather than an agreement, who is still short and why.
        The numbers come last, for anyone checking the arithmetic."""
        pick = run.last_pick or {}
        run.saving = True
        key = agreed.decision_key(run.task or ep.short_id)
        ratings = pick.get("ratings") or {}
        agreed_by_all = pick.get("outcome") == "feasible"
        label = str(pick.get("pick") or "")
        options = []
        for o in pick.get("options") or []:
            options.append(f"- **{o['label']}.** {o['text']}")
            options += [f"  - why ({h}): {w}" for h, w in (o.get("why") or {}).items() if w]
        verdict = (
            "Everyone meets the bar."
            if agreed_by_all
            else f"Best found, below the bar: {choosing.summary(pick)}"
        )
        views = "\n".join(f"- {v}" for v in choosing.views(pick, label))
        considered = "\n".join(options)
        body = (
            f"# Decision: {run.title or run.task or 'this task'}\n\n"
            f"Going with {label}: {pick.get('text')}\n\n{verdict}\n\n"
            f"{run.bar_said()}\n\n"
            f"## How each member sees it\n\n{views}\n\n"
            f"## Options considered\n\n{considered}\n\n"
            f"## The numbers\n\n{choosing.numbers(pick)}\n"
        )
        saved = await agreed.save(
            managed.room,
            key,
            body=body,
            meta={
                agreed.DECISION_META: {
                    "pick": label,
                    "text": pick.get("text"),
                    "agreed": agreed_by_all,
                    "threshold": pick.get("threshold"),
                    "outcomes": {"bad": run.settings.bad, "ideal": run.settings.ideal},
                    "views": choosing.views(pick, label) if label else [],
                    "short": pick.get("short") or [],
                    "ratings": ratings,
                    "standing": pick.get("standing") or {},
                    "options": pick.get("options") or [],
                    "cast": list(run.handles),
                },
                "flow": run.protocol.name,
                "record": f"{EPISODES_PREFIX}{ep.short_id}",
            },
            task=run.task,
            by=me,
            tags=["decision"],
        )
        run.saved_to = key if saved else None
        ep.memory = run.saved_to

    async def _take(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: episode_state.EpisodeState,
        me: str,
        step: Step,
        cap: int,
    ) -> list[tuple[str, str | None]]:
        """Put one step to its targets; return each target's stance.

        A step that collects adds what the replies carried to the run; one that
        requires something asks, once, whoever replied without it.
        """
        before = len(run.options)
        stances = await self._ask(managed, run, ep, me, step, cap)
        replied = set(run.answers)
        if step.collect == "pieces":
            run.added = 0
        await self._gather(managed, run, me, step, list(run.answers))
        if step.collect == "options" and step.to == protocols.BOTTLENECK:
            await self._refuse_a_repeat(managed, run, ep, me, step, cap, before)
        lacking = self._lacking(run, step, stances)
        if lacking and run.steps_taken < cap:
            stances = await self._reask(managed, run, ep, me, step, cap, lacking, stances)
        if step.reply is not None and step.collect == "scores":
            # A score still owed after its retry is missing, and stays so.
            for h in run.targets(step):
                if owed := run.owed(h):
                    run.unrated.setdefault(h, set()).update(owed)
        if step.needs == "pieces":
            await self._keep_unlabelled(managed, run, me, lacking)
        if step.needs == "scores":
            run.rated_upto = len(run.options)
        if step.needs == "stance":
            # Someone who wrote back but never marked a stance, even when asked
            # again, objected: a written objection is never read as consent.
            stances = [(h, "reject" if h in replied and s is None else s) for h, s in stances]
        return stances

    async def _refuse_a_repeat(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: episode_state.EpisodeState,
        me: str,
        step: Step,
        cap: int,
        before: int,
    ) -> None:
        """A fix has to be something new. One that is an option already on the
        table, or nearly the same text, is taken back and the fixer is asked
        once more for something that answers the objections. A second repeat
        stands: the next rating round, or the lack of one, says what it's worth."""
        fixer = next(iter(run.targets(step)), None)
        if fixer is None or fixer not in run.answers or fixer in run.repeat_refused:
            return
        if run.steps_taken >= cap:
            return
        added = run.options[before:]
        if added:
            newest = added[-1]
            same = await asyncio.to_thread(self._near, run, newest.text, run.options[:before])
            if same is not None:
                run.options.pop()
        else:
            if step.reply is not None:
                option = self._read(run, step, fixer)["value"].get("candidate", "")
            else:
                prose = markers.MARKER_RE.sub("", run.replies.get(fixer, "")).strip()
                option, _why = markers.split_why(prose)
            same = (
                next((o for o in run.options if choosing.same_text(o.text, option)), None)
                if option
                else None
            )
        if same is None:
            return
        run.repeat_refused.add(fixer)
        run.steps_taken += 1
        prompt = (
            f"{run.protocol.name} · {step.id} (again) · turn {run.steps_taken} of {cap} · {fixer}\n\n"
            f"That's option {same.label} again, or very close to it. A fix has to be "
            "something new that answers these objections, not the same option or a small "
            f"change to it:\n\n{run.objections()}\n\nReply with the option, then a line "
            "saying what it answers and how:\n\n<the option>\nwhy: <what it answers>"
        )
        if step.reply is not None:
            prompt = (
                f"That's {same.label} again, or very close to it. A repair has to be a new "
                "candidate that answers the reasoning against the incumbent, not a candidate "
                "already scored or a small change to one. Here is the repair again.\n\n"
                f"{step.prompt.format_map(run.fields())}"
            )
        self._manager.hold_floor(managed.room, run.episode, holder=me, speakers=[fixer])
        run.answers = {}
        run.asking, run.again = step, True
        line = turn_line(run, step, fixer, cap=cap, round_n=1) | {"again": True}
        await self._turn(
            managed,
            ep,
            me,
            run,
            fixer,
            prompt,
            {"step": step.id, "protocol": run.protocol.name, LINE_KEY: line},
        )
        await self._gather(managed, run, me, step, list(run.answers))
        ep.trace.append(
            {
                "step": step.id,
                "turn": run.steps_taken,
                "again": True,
                "asked": [fixer],
                "repeat_of": same.label,
                "at": datetime.now(UTC).isoformat(),
            }
        )

    @staticmethod
    def _near(run: Run, text: str, options: list[choosing.Option]) -> choosing.Option | None:
        """The option ``text`` repeats: the same words, or (with the embedding
        model) a near-identical meaning."""
        for o in options:
            if choosing.same_text(o.text, text):
                return o
        if run.similar is None:
            return None
        for o in options:
            try:
                if float(run.similar(o.text, text)) >= REPEAT_SIMILARITY:
                    return o
            except Exception:
                logger.warning(
                    "similarity unavailable; repeats checked by text only", exc_info=True
                )
                return None
        return None

    def _collect(self, run: Run, step: Step, answered: list[str]) -> None:
        """Add what the replies of ``answered`` carried, in cast order (whatever
        order they arrived in): options with why they were proposed, ratings of
        the options on the table with their reasons, ratings of the two
        reference outcomes, or the key terms members named."""
        order = [h for h in run.handles if h in answered]
        if step.reply:
            self._collect_replies(run, step, order)
            return
        if step.collect == "options":
            for handle in order:
                # The prose without any marker; a reply that was only a marker
                # proposed nothing, so it puts nothing on the table.
                prose = markers.MARKER_RE.sub("", run.replies.get(handle, "")).strip()
                option, why = markers.split_why(prose)
                if option:
                    choosing.add_option(run.options, option, handle, why)
        elif step.needs == "scores":
            labels = {o.label for o in run.options}
            for handle in order:
                given = markers.rated_of(run.answers[handle])
                kept = {k: v for k, v in given.items() if k in labels}
                if kept:
                    run.ratings.setdefault(handle, {}).update({k: v for k, (v, _w) in kept.items()})
                    run.reasons.setdefault(handle, {}).update(
                        {k: w for k, (_v, w) in kept.items() if w}
                    )
        elif step.collect == "anchors":
            for handle in order:
                said = markers.anchor_lines(run.replies.get(handle, ""))
                if "bad" in said and "ideal" in said and said["ideal"][0] > said["bad"][0]:
                    run.anchors[handle] = (said["bad"][0], said["ideal"][0])
        elif step.collect == "keywords":
            run.key_terms = self._key_terms(run, order)

    @staticmethod
    def _read(run: Run, step: Step, handle: str) -> dict[str, Any]:
        """``handle``'s reply to ``step``, read against the step's schema: the
        same read the hub put on the message when it was recorded."""
        assert step.reply is not None
        return reply_shape.read(
            step.reply,
            run.answers.get(handle) or {},
            candidates=run.owed(handle),
            anchor=run.anchors.get(handle),
        )

    @staticmethod
    def candidate_id(run: Run, step: Step, handle: str) -> str:
        """A candidate's id, as CONCORD names it: ``seed-<member>`` for a first
        proposal, ``r<N>-<member>`` for the one repair round ``N`` asked for."""
        if step.to == protocols.BOTTLENECK:
            return f"r{sum(run.repairs.values())}-{handle}"
        return f"seed-{handle}"

    def _collect_replies(self, run: Run, step: Step, order: list[str]) -> None:
        """What replies written in the step's schema add: a member's anchors,
        its candidate, or its scores. Only what parsed counts; a reply that
        didn't is kept as the text it is."""
        for handle in order:
            reply = self._read(run, step, handle)
            value = reply["value"]
            if step.collect == "anchors" and reply["parsed"]:
                run.anchors[handle] = (value["raw_reject"], value["raw_ideal"])
            elif step.collect == "options" and reply["parsed"]:
                choosing.add_option(
                    run.options,
                    value["candidate"],
                    handle,
                    value["rationale"],
                    label=self.candidate_id(run, step, handle),
                )
            elif step.collect == "scores":
                for s in value.get("scores") or []:
                    run.ratings.setdefault(handle, {})[s["candidate_id"]] = s["raw"]
                    if s["reasoning"]:
                        run.reasons.setdefault(handle, {})[s["candidate_id"]] = s["reasoning"]

    @staticmethod
    def _key_terms(run: Run, order: list[str]) -> list[str]:
        """The key terms members named (``term: …`` lines), the most named first
        and then in the order they were first named; five at most."""
        named: dict[str, tuple[str, int, int]] = {}
        for handle in order:
            seen: set[str] = set()
            for text in markers.term_names(run.replies.get(handle, "")):
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                shown, count, first = named.get(key, (text, 0, len(named)))
                named[key] = (shown, count + 1, first)
        ranked = sorted(named.values(), key=lambda v: (-v[1], v[2]))
        return [shown for shown, _c, _f in ranked[:5]]

    async def _gather(
        self, managed: ManagedRoomChannel, run: Run, me: str, step: Step, answered: list[str]
    ) -> None:
        """What the replies of ``answered`` add to the run: options, ratings, or
        labelled pieces merged into the frame (off the loop, since merging can
        ask the embedding model), with a note in the thread for anything a
        bound dropped."""
        if step.collect != "pieces":
            self._collect(run, step, answered)
            return
        order = [h for h in run.handles if h in answered]
        replies = [(h, markers.pieces_of(run.answers[h], run.key_terms)) for h in order]
        folded = await asyncio.to_thread(framing.fold, run.frame, replies, similar=run.similar)
        run.added += len(folded.added)
        if folded.notes:
            await self._say(managed, run.episode, me, " ".join(folded.notes))

    async def _keep_unlabelled(
        self, managed: ManagedRoomChannel, run: Run, me: str, lacking: list[str]
    ) -> None:
        """A reply that still carries no label, even when asked again, is kept
        whole as one unlabelled statement by its writer: never lost, never
        guessed into a type."""
        for handle in lacking:
            if handle in run.answers and markers.pieces_of(run.answers[handle], run.key_terms):
                continue
            text = markers.MARKER_RE.sub("", run.replies.get(handle, "")).strip()
            if not text:
                continue
            kept = await asyncio.to_thread(
                framing.add_statement, run.frame, handle, text, similar=run.similar
            )
            run.added += len(kept.added)
            if kept.notes:
                await self._say(managed, run.episode, me, " ".join(kept.notes))

    @staticmethod
    def _lacking(run: Run, step: Step, stances: list[tuple[str, str | None]]) -> list[str]:
        """Who replied without what the step requires. Silence is not lacking,
        so a member who didn't answer isn't asked again, except for CONCORD's
        scores: a score still missing after its retry is marked missing."""
        if step.reply is not None:
            if step.collect == "scores":
                return [h for h in run.targets(step) if run.owed(h)]
            if step.collect == "anchors":
                return [h for h in run.handles if h in run.answers and h not in run.anchors]
            return [
                h
                for h in run.handles
                if h in run.answers and not ConductorEngine._read(run, step, h)["parsed"]
            ]
        if step.needs == "pieces":
            return [
                h
                for h in run.handles
                if h in run.answers
                and not markers.pieces_of(run.answers[h], run.key_terms)
                and markers.MARKER_RE.sub("", run.replies.get(h, "")).strip()
            ]
        if step.needs == "scores":
            # A rating has to come with its reason: the reason is the argument.
            wanted = {o.label for o in run.new_options()}
            return [
                h
                for h in run.handles
                if h in run.answers
                and not (
                    wanted <= set(run.ratings.get(h, {})) and wanted <= set(run.reasons.get(h, {}))
                )
            ]
        if step.needs == "anchors":
            return [h for h in run.handles if h in run.answers and h not in run.anchors]
        if step.needs == "stance":
            return [h for h, s in stances if s is None and h in run.answers]
        return []

    @classmethod
    def _asked_again(cls, run: Run, step: Step, handle: str) -> str:
        """The one retry a reply in a schema gets: what it lacked, in a line,
        then the message again as it was sent."""
        message = step.prompt.format_map(run.fields())
        if handle not in run.answers:
            return f"No reply came to this, so here it is again.\n\n{message}"
        missing = cls._read(run, step, handle).get("missing") or []
        if step.collect == "anchors" and not missing:
            missing = ["raw_ideal above raw_reject"]
        lacked = ", ".join(missing) or "what it asks for"
        return (
            f"Your reply didn't have {lacked}. Here is the message again: reply with the "
            f"element it shows, filled in.\n\n{message}"
        )

    async def _reask(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: episode_state.EpisodeState,
        me: str,
        step: Step,
        cap: int,
        lacking: list[str],
        stances: list[tuple[str, str | None]],
    ) -> list[tuple[str, str | None]]:
        """One more turn for just ``lacking``, at once, as its own step."""
        run.steps_taken += 1
        if step.needs == "scores":
            # Restate what's being rated: the re-ask arrives on its own, and a
            # member can't rate options it can't see.
            fresh = run.new_options()
            lines = _rating_lines(fresh, run.options)
            ask = (
                "I couldn't read a rating with a reason for each of these options:\n\n"
                f"{run._listed(fresh)}\n\nRate each for your role, on the scale you rated "
                f"the two outcomes on, one line each with your reason:\n\n{lines}"
            )
        elif step.needs == "anchors":
            ask = (
                "I couldn't read your ratings of the two outcomes, or your ideal wasn't "
                f"rated above the bad one.\n\nbad: {run.settings.bad}\nideal: "
                f"{run.settings.ideal}\n\nRate each from 0 to 100 on your own scale, "
                "one line each, with why:\n\nbad: <0-100> - <why>\nideal: <0-100> - <why>"
            )
        elif step.needs == "pieces":
            ask = (
                "I couldn't find a labelled line in your reply, so I can't tell what kind "
                "of point each part is. Say it again with each point on its own line, "
                "starting with what kind it is, like `constraint: the limit`. The kinds "
                f"are {', '.join(markers.POINT_TYPES)}. Whatever you send without one is "
                "kept as you wrote it."
            )
        else:
            ask = (
                "I couldn't tell whether you accept this. End your reply with "
                "[[mycelium: stance=accept]] or [[mycelium: stance=reject]]."
            )
        head = f"{run.protocol.name} · {step.id} (again) · turn {run.steps_taken} of {cap}"
        texts = {h: f"{head} · {h}\n\n{ask}" for h in lacking}
        if step.reply is not None:
            # Said before the answers are cleared: what each member's reply lacked.
            texts = {h: self._asked_again(run, step, h) for h in lacking}
        self._manager.hold_floor(managed.room, run.episode, holder=me, speakers=lacking)
        run.answers = {}
        run.asking, run.again = step, True
        again = dict(
            await asyncio.gather(
                *(
                    self._turn(
                        managed,
                        ep,
                        me,
                        run,
                        h,
                        texts[h],
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
        await self._gather(managed, run, me, step, list(run.answers))
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
        ep: episode_state.EpisodeState,
        me: str,
        step: Step,
        cap: int,
    ) -> list[tuple[str, str | None]]:
        """Put one step to its targets; return each target's stance."""
        room = managed.room
        targets = run.targets(step)
        stances: list[tuple[str, str | None]] = []
        run.answers = {}
        run.asking, run.again = step, False

        def render(handle: str, round_n: int) -> str:
            body = step.prompt.format_map(run.fields(round_n=round_n, rounds=step.rounds))
            if step.reply:
                # A protocol's own message goes as written, with nothing before
                # it: the turn's place in the run rides its structured line.
                return body
            # Every turn says which step of which flow it is, so the episode
            # reads as a run and not as a conversation that happened to occur.
            head = f"{run.protocol.name} · {step.id} · turn {run.steps_taken} of {cap} · {handle}"
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
            if step.to in ("all", "workers", protocols.CONTESTED):
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
        ep: episode_state.EpisodeState,
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

        run.waiting.add(pending)
        try:
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
                on_tick=lambda env: ep.messages.append(message_format.envelope_to_dict(env)),
                on_reply=on_reply,
            )
        finally:
            run.waiting.discard(pending)
        if not answered:
            return handle, "silent"
        run.replies[handle] = prose
        run.recent = prose
        run.answers[handle] = answered[-1].content
        return handle, markers.stance_of(answered[-1].content)

    async def _tell(
        self,
        managed: ManagedRoomChannel,
        ep: episode_state.EpisodeState,
        me: str,
        run: Run,
        handle: str,
        prompt: str,
        data: dict[str, Any],
    ) -> None:
        """A fire-and-forget step: say it to one member and move on."""
        env = message_format.build_envelope(
            kind=Kind.exchange,
            episode=run.episode,
            sender=me,
            recipients=[handle],
            topic=ep.topic,
            payload_type="message",
            payload_data=data,
        )
        ep.messages.append(message_format.envelope_to_dict(env))
        try:
            await managed.post(env, prompt)
        except Exception:
            logger.warning("conductor failed to post step %s to @%s", data.get("step"), handle)

    async def _close(
        self,
        managed: ManagedRoomChannel,
        run: Run,
        ep: episode_state.EpisodeState,
        me: str,
        outcome: str,
        why: str,
    ) -> None:
        """Commit the outcome onto the thread and write the run's record.

        A run that picked carries its last pick; an agreement commits
        ``converged`` and its decision is saved to the room's memory first, so
        the commit can point at it. A conductor run files no board rows: the
        commit carries no ``assignments`` for the compile seam to turn into work.
        """
        pick = run.last_pick
        run.walked = len(ep.trace)
        if outcome in ("converged", "resolved") and pick is not None and pick.get("pick"):
            # An agreement, or the best found when the fixes ran out: either way
            # it's the answer the run gives, saved for the work that follows.
            await self._save_decision(managed, run, ep, me)
        data: dict[str, Any] = {
            "protocol": run.protocol.name,
            "steps": run.walked,
            "reason": why,
            "roles": run.bound,
            "record": f"{EPISODES_PREFIX}{ep.short_id}",
            LINE_KEY: close_line(run, outcome, why),
        }
        metrics = None
        if pick is not None:
            data["select"] = pick
            # Satisfaction is where each member placed the pick between its own
            # bad and ideal outcomes, so one member's number means what another's does.
            standing: dict[str, float] = pick.get("standing") or {}
            if standing:
                metrics = {
                    "satisfaction": dict(standing),
                    "min_satisfaction": min(standing.values()),
                }
                data["metrics"] = metrics
        if run.saving:
            # Where the shared summary or the decision was saved; null when the
            # write failed, so a reader can tell that from a run that saved none.
            data["memory"] = run.saved_to
        commit = message_format.build_envelope(
            kind=Kind.commit,
            subkind=outcome,
            episode=run.episode,
            sender=me,
            recipients=run.handles,
            topic=ep.topic,
            payload_type="outcome",
            payload_data=data,
        )
        ep.messages.append(message_format.envelope_to_dict(commit))
        text = f"{self._result_line(run, outcome, why)} Record: {EPISODES_PREFIX}{ep.short_id}."
        said = concord_commit(run, outcome)
        winner = next((o for o in run.options if o.label == (pick or {}).get("pick")), None)
        if said is not None and winner is not None:
            # CONCORD ends with its commit, sent to every member; the line a
            # person reads follows it.
            element = concord_messages.commit(
                said["outcome"], run.candidate(winner), run.scored(winner.label), run.bar()
            )
            text = f"{element}\n\n{text}"
        try:
            # A commit asks nobody (``asks.py``): the close is said, not put.
            await managed.post(commit, text, list_write=True)
        except Exception:
            logger.warning("conductor failed to post the outcome for %s", run.episode)
        episode_state.write_episode_record(ep, outcome=outcome, metrics=metrics, tasks=None)
        self._stepped(managed.room, run.episode, outcome)
        from app.services import analytics as usage

        await asyncio.to_thread(usage.flow_completed, run.protocol.name, outcome, run.walked)
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
            if run.made is not None:
                numbers = framing.counts(run.made)
                flagged = [f["text"] for f in run.made["flags"] if f["kind"] != "quiet_member"]
                said = f" {_counted(numbers)}"
                if flagged:
                    said += f" Flagged: {'; '.join(flagged)}."
                quiet = numbers["quiet"]
                said += f" No answer from {', '.join(quiet)}." if quiet else ""
                return (
                    f"{mark} {run.protocol.name}: {outcome} after {run.walked} step(s)."
                    f"{said}{_saved(run, 'shared summary')}"
                )
            # The close says who was silent at the last step, so a step that
            # went on without someone shows whose answer it went on without.
            quiet = f" No answer from {', '.join(run.quiet)}." if run.quiet else ""
            return (
                f"{mark} {run.protocol.name}: {outcome} after {run.walked} step(s), {why}.{quiet}"
            )
        label, text = pick["pick"], pick["text"]
        if outcome == "converged":
            answered = ""
            if run.first_short is not None:
                who, objection = run.first_short
                if objection:
                    answered = f" It answers {who}'s objection: {_sentence(objection)}"
            return (
                f"✓ Everyone meets the bar: going with {label}: {_sentence(text)}{answered}"
                f"{_saved(run, 'decision')}"
            )
        if outcome == "resolved":
            return (
                f"Best found: {label}: {_sentence(text)} It's below the bar for some: "
                f"{choosing.summary(pick)}{_saved(run, 'decision')}"
            )
        return (
            f"✗ Couldn't get everyone there. Best was {label}: {_sentence(text)} "
            f"{choosing.summary(pick)}"
        )

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
        env = message_format.build_envelope(
            kind=Kind.exchange,
            episode=episode,
            sender=sender,
            topic=message_format.topic_urn(managed.room),
            payload_type="message",
            payload_data={LINE_KEY: line} if line else None,
        )
        try:
            # Posted as written: a mention asks whoever it names, as anyone's
            # does (``asks.py``). The conductor's own lines name no one bare.
            await managed.post(env, text, list_write=True)
        except Exception:
            logger.warning("conductor failed to post on room %s", managed.room)
