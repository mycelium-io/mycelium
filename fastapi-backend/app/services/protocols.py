# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Protocols — the shapes a conductor runs a thread through.

A protocol is a small graph of **steps**. Each step puts a prompt to one
member, to each in turn, or to several at once, waits for what comes back,
and names the step after it — by one edge, or by one edge per stance the
reply took. The graph is data, not cognition: the conductor walks it in code
and the only judgment in a run is inside the members it addresses.

Several protocols ship built in, and a room can add its own or override one
of these by writing a ``protocols/<name>`` memory whose body is the same YAML
(:func:`load_protocol`). Like skills, a protocol is a memory promoted: no
separate store, and one is readable as a memory too.

Step targets: a **role** the summon bound (``@conductor gated @a @b`` binds
``a`` and ``b`` to the protocol's roles in order), ``each`` (every member,
one at a time), ``all`` (every member, at once), ``workers`` (every member
not bound to a named role, at once), ``bottleneck`` (the member the latest
pick left least happy) or ``contested`` (the members the latest tally of
words found using one in different senses).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

#: The memory namespace protocols live in.
PROTOCOLS_PREFIX = "protocols/"

#: What a step may be put to besides a role.
GROUP_TARGETS = frozenset({"each", "all", "workers"})

#: The one member the latest ``select`` step found least happy with its pick.
BOTTLENECK = "bottleneck"

#: The stances an edge can branch on, plus the two fallbacks.
EDGE_KEYS = frozenset({"accept", "reject", "silent", "default"})

#: Everyone who gave a meaning to a word the latest ``tally`` of terms found
#: used in different senses.
CONTESTED = "contested"

#: How a ``select`` step's pick went: everyone's on board, someone can fix it,
#: or a fix can't help.
SELECT_EDGES = frozenset({"feasible", "infeasible", "stuck", "default"})

#: How a ``tally`` went. Of points: the last round added some, added none, or
#: nobody has given any. Of terms: a word is used in different senses, or not.
TALLY_EDGES = {
    "points": frozenset({"grew", "settled", "empty", "default"}),
    "terms": frozenset({"contested", "clear", "default"}),
}

#: How a ``lock`` went: the shared summary was assembled, or there was nothing
#: to assemble it from.
LOCK_EDGES = frozenset({"locked", "empty", "default"})

#: Steps that ask nobody: code decides where they lead.
CODE_KINDS = frozenset({"select", "tally", "lock"})

#: ``converged`` is the end an agreement a ``select`` step certified reaches.
#: Every other flow ends ``resolved`` or ``rejected``.
Outcome = Literal["resolved", "rejected", "converged"]

#: The outcomes that read as success wherever a run's end is drawn.
SUCCESS = frozenset({"resolved", "converged"})

DEFAULT_THRESHOLD = 0.7
DEFAULT_MAX_REPAIRS = 2
#: How many rounds a tally lets its points or words go before it settles.
DEFAULT_MAX_ROUNDS = {"points": 3, "terms": 2}


class Step(BaseModel):
    """One step: who is asked what, and where the reply leads.

    A ``select`` step asks nobody: it picks among the options the members
    suggested, by the ratings they gave (:mod:`app.services.select`), and
    branches on whether everyone is on board. A ``tally`` asks nobody either:
    it reads the points or words the members labelled (:mod:`app.services.frame`)
    and branches on whether the last round added any, or whether a word is
    used in different senses. A ``lock`` assembles everything gathered into
    the shared summary and saves it to the room's memory.
    """

    id: str = Field(..., min_length=1)
    kind: Literal["ask", "select", "tally", "lock"] = "ask"
    to: str | None = Field(
        None,
        description=(
            "A role, or each / all / workers / bottleneck / contested. Absent on an "
            "end step and on a step that asks nobody."
        ),
    )
    prompt: str = ""
    wait: Literal["reply", "none"] = "reply"
    rounds: int = Field(1, ge=1, description="How many times an each/all step repeats.")
    collect: Literal["options", "scores", "pieces"] | None = Field(
        None,
        description=(
            "What the replies add to the run: each reply becomes an option, each "
            "reply's ratings are recorded, or each reply's labelled pieces (points, "
            "words, checks) are merged into the frame."
        ),
    )
    require: Literal["stance", "scores", "pieces"] | None = Field(
        None,
        description=(
            "What every reply must carry. A reply without it is asked once more; "
            "an unmarked stance after that counts as reject, and unlabelled text "
            "is kept as one unlabelled statement."
        ),
    )
    threshold: float | None = Field(
        None, ge=0, le=1, description="A select step's bar, 0-1 (0.7 = everyone rates it 70+)."
    )
    max_repairs: int | None = Field(
        None, ge=0, description="How many fixes a select step sends for before it is stuck."
    )
    of: Literal["points", "terms"] | None = Field(
        None, description="What a tally step reads: the points gathered, or the words."
    )
    max_rounds: int | None = Field(
        None,
        ge=1,
        description=(
            "How many times a tally can run before it settles: points still being "
            "added, or words still used in different senses, are then flagged."
        ),
    )
    next: str | dict[str, str] | None = Field(
        None,
        description=(
            "The step after this one: a step id, or a map of accept / reject / "
            "silent / default (a select: feasible / infeasible / stuck; a tally of "
            "points: grew / settled / empty; of terms: contested / clear; a lock: "
            "locked / empty; each with default) to step ids."
        ),
    )
    end: Outcome | None = Field(None, description="Set on a terminal step: how the run ends.")

    @property
    def needs(self) -> str | None:
        """What a reply to this step must carry; collecting ratings requires them."""
        return self.require or ("scores" if self.collect == "scores" else None)

    @model_validator(mode="after")
    def _terminal_or_addressed(self) -> Step:
        if self.end is not None:
            if self.to is not None or self.next is not None or self.kind != "ask":
                msg = f"step {self.id!r} ends the run and cannot also address, pick or continue"
                raise ValueError(msg)
            return self
        if self.kind in CODE_KINDS and (
            self.to is not None or self.prompt or self.collect or self.require
        ):
            msg = (
                f"{self.kind} step {self.id!r} asks nobody: it takes no to, prompt, "
                "collect or require"
            )
            raise ValueError(msg)
        if self.kind != "select" and (self.threshold is not None or self.max_repairs is not None):
            msg = f"step {self.id!r}: threshold and max_repairs belong to a select step"
            raise ValueError(msg)
        if self.kind != "tally" and (self.of is not None or self.max_rounds is not None):
            msg = f"step {self.id!r}: of and max_rounds belong to a tally step"
            raise ValueError(msg)
        if self.kind == "select":
            return self._a_select()
        if self.kind == "tally":
            return self._a_tally()
        if self.kind == "lock":
            return self._branches(LOCK_EDGES)
        if self.collect == "scores" and self.require not in (None, "scores"):
            msg = f"step {self.id!r} collects ratings, so it requires ratings, not a stance"
            raise ValueError(msg)
        if self.require == "pieces" and self.collect != "pieces":
            msg = f"step {self.id!r} requires labelled pieces, so it must collect them"
            raise ValueError(msg)
        if not self.to:
            msg = f"step {self.id!r} addresses nobody and ends nothing"
            raise ValueError(msg)
        return self._branches(EDGE_KEYS)

    def _a_select(self) -> Step:
        if not isinstance(self.next, dict):
            msg = f"select step {self.id!r} branches by map: {sorted(SELECT_EDGES)}"
            raise ValueError(msg)
        # Written out, so the flow as the app reads it carries the bar.
        if self.threshold is None:
            self.threshold = DEFAULT_THRESHOLD
        if self.max_repairs is None:
            self.max_repairs = DEFAULT_MAX_REPAIRS
        return self._branches(SELECT_EDGES)

    def _a_tally(self) -> Step:
        if self.of is None:
            msg = f"tally step {self.id!r} needs of: points or of: terms"
            raise ValueError(msg)
        if not isinstance(self.next, dict):
            msg = f"tally step {self.id!r} branches by map: {sorted(TALLY_EDGES[self.of])}"
            raise ValueError(msg)
        # Written out, like a select's bar, so the app can say the cap.
        if self.max_rounds is None:
            self.max_rounds = DEFAULT_MAX_ROUNDS[self.of]
        return self._branches(TALLY_EDGES[self.of])

    def _branches(self, allowed: frozenset[str]) -> Step:
        if self.next is None:
            msg = f"step {self.id!r} names no next step"
            raise ValueError(msg)
        if isinstance(self.next, dict):
            unknown = set(self.next) - allowed
            if unknown:
                msg = f"step {self.id!r} branches on {sorted(unknown)}; edges are {sorted(allowed)}"
                raise ValueError(msg)
            if not self.next:
                msg = f"step {self.id!r} has an empty branch map"
                raise ValueError(msg)
        return self

    def edge(self, stance: str | None) -> str:
        """The next step id for a reply that took ``stance`` (``None`` = none stated,
        ``"silent"`` = no reply at all)."""
        if isinstance(self.next, str):
            return self.next
        assert self.next is not None  # validated on construction
        if stance and stance in self.next:
            return self.next[stance]
        if "default" in self.next:
            return self.next["default"]
        # No fallback named: a branch map with only accept/reject reads a
        # non-answer as the reject edge when it has one, else the first edge.
        return self.next.get("reject") or next(iter(self.next.values()))


class Protocol(BaseModel):
    """A named, validated step graph."""

    name: str = Field(..., min_length=1)
    description: str = ""
    roles: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(..., min_length=1)
    max_steps: int = Field(12, ge=1, description="Hard cap on steps taken in one run.")

    @field_validator("roles")
    @classmethod
    def _roles_are_distinct_names(cls, roles: list[str]) -> list[str]:
        clean = [r.strip().lower() for r in roles]
        if any(not r for r in clean):
            msg = "a role name cannot be empty"
            raise ValueError(msg)
        if len(set(clean)) != len(clean):
            msg = "role names must be distinct"
            raise ValueError(msg)
        reserved = set(clean) & (GROUP_TARGETS | {BOTTLENECK, CONTESTED})
        if reserved:
            msg = f"a role cannot be named {sorted(reserved)}"
            raise ValueError(msg)
        return clean

    @model_validator(mode="after")
    def _graph_is_closed(self) -> Protocol:
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            msg = "step ids must be distinct"
            raise ValueError(msg)
        known = set(ids)
        for step in self.steps:
            if (
                step.to is not None
                and step.to not in GROUP_TARGETS
                and step.to not in (BOTTLENECK, CONTESTED)
                and step.to not in self.roles
            ):
                msg = f"step {step.id!r} addresses {step.to!r}, which is neither a role nor a group"
                raise ValueError(msg)
            for target in _targets_of(step):
                if target not in known:
                    msg = f"step {step.id!r} continues to {target!r}, which is not a step"
                    raise ValueError(msg)
        if not any(s.end for s in self.steps):
            msg = "a protocol needs at least one end step"
            raise ValueError(msg)
        # ``to: bottleneck`` names whoever the latest pick found least happy;
        # ``to: contested``, whoever the latest tally of words found using one
        # in a different sense. Either has to be defined before it is asked.
        self._target_follows(
            BOTTLENECK, lambda s: s.kind == "select", "infeasible", "the bottleneck", "select"
        )
        self._target_follows(
            CONTESTED,
            lambda s: s.kind == "tally" and s.of == "terms",
            "contested",
            "the contested",
            "tally of terms",
        )
        self._converged_is_certified()
        return self

    def _target_follows(
        self,
        target: str,
        defines: Callable[[Step], bool],
        edge: str,
        said: str,
        definer: str,
    ) -> None:
        """Every path from the first step to a step addressed to ``target`` has to
        pass a step that ``defines`` it, and of those steps' edges only ``edge``
        may lead straight to one: on any other way out there is nobody to ask."""
        by_id = {s.id: s for s in self.steps}
        seen: set[str] = set()
        frontier = [self.first.id]
        while frontier:
            step = by_id[frontier.pop()]
            if step.id in seen:
                continue
            seen.add(step.id)
            if step.to == target:
                msg = f"step {step.id!r} asks {said}, but a path reaches it before any {definer}"
                raise ValueError(msg)
            if defines(step):
                continue  # past it, the target is defined
            frontier.extend(_targets_of(step))
        for step in self.steps:
            if not defines(step):
                continue
            for key, then in _edges_of(step):
                if key != edge and by_id[then].to == target:
                    msg = (
                        f"{step.kind} {step.id!r} goes to {said} on {key!r}; "
                        f"only its {edge} edge has one"
                    )
                    raise ValueError(msg)

    def _converged_is_certified(self) -> None:
        """An end of ``converged`` is reached only from a pick's ``feasible`` edge."""
        for end in self.steps:
            if end.end != "converged":
                continue
            ways_in = [
                (s, key) for s in self.steps for key, target in _edges_of(s) if target == end.id
            ]
            if not ways_in or any(s.kind != "select" or key != "feasible" for s, key in ways_in):
                msg = f"end {end.id!r} is converged, so only a select's feasible edge may reach it"
                raise ValueError(msg)

    @property
    def first(self) -> Step:
        return self.steps[0]

    def step(self, step_id: str) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)


def _edges_of(step: Step) -> list[tuple[str, str]]:
    """``(edge key, target)`` for each way out of a step; a plain edge is keyed ``""``."""
    if isinstance(step.next, str):
        return [("", step.next)]
    return list((step.next or {}).items())


def _targets_of(step: Step) -> list[str]:
    return [target for _key, target in _edges_of(step)]


# ── the built-ins ─────────────────────────────────────────────────────────────

BUILTIN_PROTOCOLS: dict[str, dict[str, Any]] = {
    "round-robin": {
        "name": "round-robin",
        "description": "Every member speaks in turn, for a fixed number of rounds.",
        "roles": [],
        "max_steps": 12,
        "steps": [
            {
                "id": "round",
                "to": "each",
                "rounds": 2,
                "prompt": (
                    "Round {round} of {rounds}.\n\nThe question: {ask}\n\n"
                    "What has been said so far:\n{replies}\n\n"
                    "Give your position in a few sentences, answering what the "
                    "others said where it matters."
                ),
                "next": "done",
            },
            {"id": "done", "end": "resolved"},
        ],
    },
    "fan-out": {
        "name": "fan-out",
        "description": "A lead asks every worker at once, then combines what came back.",
        "roles": ["lead"],
        "max_steps": 6,
        "steps": [
            {
                "id": "gather",
                "to": "workers",
                "prompt": (
                    "{ask}\n\nAnswer with what you can contribute, what you would "
                    "need, and any blocker you see. A few sentences."
                ),
                "next": "combine",
            },
            {
                "id": "combine",
                "to": "lead",
                "prompt": (
                    "You asked the team: {ask}\n\nThey answered:\n{replies}\n\n"
                    "Combine those into one plan: say who does what, and name "
                    "anything that is still unresolved."
                ),
                "next": "done",
            },
            {"id": "done", "end": "resolved"},
        ],
    },
    "swarm": {
        "name": "swarm",
        "description": "A team kicks off a task: each member checks in, then the lead splits the work.",
        "roles": ["lead"],
        "max_steps": 4,
        "steps": [
            {
                "id": "check-in",
                "to": "each",
                "prompt": (
                    "The team ({handles}) is taking on task {task}: {ask}\n\n"
                    "Check in, in two or three sentences: say which part you would "
                    "take and what you would need from someone else. Answer what the "
                    "others said where it matters. If the task leaves something open, "
                    "say what you will assume rather than asking. Do not start the "
                    "work yet.\n\n"
                    "Said so far:\n{replies}"
                ),
                "next": "split",
            },
            {
                "id": "split",
                "to": "lead",
                "prompt": (
                    "Everyone has checked in on {task}: {ask}\n\n{replies}\n\n"
                    "You are the lead. Split the work into child tasks of {task}, one "
                    "per piece, each given to the member who offered to take it, so "
                    "every member has one. Make them pieces that can be worked at the "
                    "same time, each producing part of the result; do not make a task "
                    "that only reviews or waits on another, since every piece is "
                    "reviewed by another member anyway. Create them now, then say the "
                    "split in a few lines."
                ),
                "next": "done",
            },
            {"id": "done", "end": "resolved"},
        ],
    },
    "review": {
        "name": "review",
        "description": (
            "An author does the work, a reviewer checks it against evidence; "
            "findings go back until the reviewer approves."
        ),
        "roles": ["author", "reviewer"],
        "max_steps": 9,
        "steps": [
            {
                "id": "build",
                "to": "author",
                "prompt": (
                    "Task {task}: {ask}\n\nDo the work on your own branch. When it is "
                    "done, say in a few lines what you changed, where (the branch and "
                    "files), and exactly how to check it."
                ),
                "next": "review",
            },
            {
                "id": "review",
                "to": "reviewer",
                "prompt": (
                    "Review the work on {task}: {ask}\n\nThe author says:\n{reply}\n\n"
                    "Check it yourself: check out the branch, run the tests and whatever "
                    "the change touches. Every finding names its evidence: the command "
                    "you ran and what came back. Approve only what you ran and saw hold; "
                    "do not approve on reading alone. End with "
                    "[[mycelium: stance=accept]] to approve or "
                    "[[mycelium: stance=reject]] with the findings to send it back."
                ),
                "next": {"accept": "approved", "reject": "fix", "default": "fix"},
            },
            {
                "id": "fix",
                "to": "author",
                "prompt": (
                    "The reviewer sent {task} back:\n\n{reply}\n\nAnswer each finding: "
                    "fix it and say how, or say why it is not a problem. Then say what "
                    "changed and how to check it again."
                ),
                "next": "review",
            },
            {"id": "approved", "end": "resolved"},
        ],
    },
    "gated": {
        "name": "gated",
        "description": "A proposer proposes, a guardian approves or blocks; a block sends it back.",
        "roles": ["proposer", "guardian"],
        "max_steps": 6,
        "steps": [
            {
                "id": "propose",
                "to": "proposer",
                "prompt": (
                    "{ask}\n\nState exactly what you intend to do, in a few "
                    "sentences. If a reviewer already objected, the objection "
                    "follows and your proposal has to answer it.\n\n{reply}"
                ),
                "next": "review",
            },
            {
                "id": "review",
                "to": "guardian",
                "prompt": (
                    "A proposal is on the table:\n\n{reply}\n\nApprove it or block "
                    "it, and say why in a sentence or two. End your reply with "
                    "[[mycelium: stance=accept]] to approve or "
                    "[[mycelium: stance=reject]] to block."
                ),
                "next": {"accept": "approved", "reject": "propose", "default": "propose"},
            },
            {"id": "approved", "end": "resolved"},
        ],
    },
    # IoC L9's Concord, cut down: suggest, rate, and a pick made in code, with
    # the least happy member asked for a fix until everyone clears the bar.
    "concord": {
        "name": "concord",
        "description": (
            "Help them agree. Everyone suggests, everyone rates, the least happy agent "
            "suggests a fix, until one option clears the bar for all."
        ),
        "roles": [],
        # A safety net: suggest, rate, 2 x (fix, re-rate), plus up to 3 re-asks.
        # max_repairs is what bounds the fixes.
        "max_steps": 9,
        "steps": [
            {
                "id": "propose",
                "to": "all",
                "collect": "options",
                # Each reply becomes an option on the table word for word, so
                # the prompt asks for the option and nothing around it.
                "prompt": (
                    "{agreed}{ask}\n\nReply with just the one option you think best serves "
                    "your role for {title}: the concrete terms, in one or two "
                    "sentences, with no preamble. Don't hedge or pre-compromise; "
                    "everyone will rate everyone's option next."
                ),
                "next": "score",
            },
            {
                "id": "score",
                "to": "all",
                "collect": "scores",
                "prompt": (
                    "The options for {title}:\n\n{options}\n\nRate each one 0-100 for "
                    "your own role: 0 means unacceptable, 100 means ideal. Give one "
                    "line on why for each, then end with [[mycelium: {option_labels}]], "
                    "one number per option."
                ),
                "next": "pick",
            },
            {
                "id": "pick",
                "kind": "select",
                "threshold": DEFAULT_THRESHOLD,
                "max_repairs": DEFAULT_MAX_REPAIRS,
                "next": {"feasible": "agreed", "infeasible": "repair", "stuck": "no_deal"},
            },
            {
                "id": "repair",
                "to": BOTTLENECK,
                "collect": "options",
                # A fix revises the best option rather than starting over, so it
                # keeps what earlier fixes added; it shows the pick's full text
                # and every option's, since the fixer can only keep what it sees.
                # It goes on the table word for word, so it asks for nothing else.
                "prompt": (
                    "The best option so far for {title} is:\n\n{pick}\n\n{shortfall}. "
                    "Reply with just a revised version of it that you'd rate {threshold} "
                    "or more: change as little as you can and keep what the others rated "
                    "high. The full terms, in one or two sentences, with no preamble or "
                    "analysis.\n\nEvery option so far:\n\n{options}\n\nHow they were "
                    "rated:\n\n{scores}"
                ),
                "next": "rescore",
            },
            {
                "id": "rescore",
                "to": "all",
                "collect": "scores",
                "prompt": (
                    "A new option for {title}:\n\n{new_options}\n\nRate it 0-100 for your "
                    "role, with one line on why, then end with [[mycelium: {new_labels}]]."
                ),
                "next": "pick",
            },
            {"id": "agreed", "end": "converged"},
            {"id": "no_deal", "end": "rejected"},
        ],
    },
    # IoC L9's Accord, cut down: everyone labels what they understand the task
    # to be, code merges it into one frame, checks the words, and saves the
    # result. No lead and no vote: what doesn't line up is flagged, not argued.
    "accord": {
        "name": "accord",
        "description": (
            "Get on the same page. Everyone says what the task is, what's out of "
            "scope, what done means and what the key words mean; it's merged into one "
            "shared summary, with anything that doesn't line up flagged, and saved."
        ),
        "roles": [],
        # Frame, its re-ask, two more rounds, the words, one restatement.
        "max_steps": 8,
        "steps": [
            {
                "id": "frame",
                "to": "all",
                "collect": "pieces",
                "require": "pieces",
                "prompt": (
                    "{agreed}Before we start on {title}: {ask}\n\nSay what you understand "
                    "the task to be. Put each point on its own line, starting with a "
                    "label for what kind of point it is:\n\n"
                    "[[mycelium: objective]] what it's for\n"
                    "[[mycelium: constraint]] a limit the work has to respect\n"
                    "[[mycelium: assumption]] something you're taking as given\n"
                    "[[mycelium: sub_goal]] a part of the work\n"
                    "[[mycelium: deliverable]] what gets handed over when it's done\n"
                    "[[mycelium: out_of_scope]] what this task does not include\n\n"
                    "Give only the points that matter most from where you sit, five "
                    "or fewer, one or two sentences each. To say what a point is "
                    "about, add about=<subject>, like [[mycelium: constraint "
                    "about=pricing]]. Everyone's points are merged in code, so say "
                    "yours plainly rather than trying to cover everyone's."
                ),
                "next": "added",
            },
            {
                "id": "added",
                "kind": "tally",
                "of": "points",
                "max_rounds": 3,
                "next": {"grew": "more", "settled": "ground", "empty": "nothing"},
            },
            {
                "id": "more",
                "to": "all",
                "collect": "pieces",
                "prompt": (
                    "What the team has said about {title} so far:\n\n{frame}\n\nIs something "
                    "important missing, something the work would go wrong without? If so, "
                    "add it on its own labelled line as before, two at most. Don't add "
                    "detail to points already there. Usually nothing is missing: then "
                    "say so in a few words, with no label."
                ),
                "next": "added",
            },
            {
                "id": "ground",
                "to": "all",
                "collect": "pieces",
                "prompt": (
                    "The points for {title}:\n\n{frame}\n\nTwo last things. For any word "
                    "you're using in a specific sense, say what you mean by it:\n\n"
                    "[[mycelium: term=<word>]] what you mean by it\n\n"
                    "And for any point you could confirm, say how, naming the points it "
                    "covers:\n\n"
                    "[[mycelium: check covers=p1,p2]] what you would do to confirm them\n\n"
                    "If there's nothing to add, say so in a few words."
                ),
                "next": "words",
            },
            {
                "id": "words",
                "kind": "tally",
                "of": "terms",
                "max_rounds": 2,
                "next": {"contested": "restate", "clear": "lock"},
            },
            {
                "id": "restate",
                "to": "contested",
                "collect": "pieces",
                "prompt": (
                    "Some words are being used in different senses:\n\n{terms}\n\n"
                    "Given what the others mean, say again what you mean by each word "
                    "you defined, with [[mycelium: term=<word>]]. Keep your meaning if "
                    "it's the one you need; nobody has to give way."
                ),
                "next": "words",
            },
            {"id": "lock", "kind": "lock", "next": {"locked": "locked", "empty": "nothing"}},
            {"id": "locked", "end": "resolved"},
            {"id": "nothing", "end": "rejected"},
        ],
    },
}


def describe(protocol: Protocol) -> str:
    """A protocol as a person reads it: its roles, then each step and its edges.

    One line per step, in the protocol's own words (``propose asks proposer,
    then review``), so a room can see the graph a run is walking without
    opening the spec.
    """
    lines = [f"**{protocol.name}**: {protocol.description}".rstrip(": ")]
    if protocol.roles:
        lines.append(f"roles: {', '.join(protocol.roles)} (bound in that order)")
    for step in protocol.steps:
        if step.end is not None:
            lines.append(f"- {step.id}: ends {step.end}")
            continue
        if step.kind == "select":
            edges = ", ".join(f"{k}: {v}" for k, v in (step.next or {}).items())  # type: ignore[union-attr]
            bar = round((step.threshold or DEFAULT_THRESHOLD) * 100)
            lines.append(
                f"- {step.id}: picks the option the least happy member likes best, bar {bar} "
                f"(up to {step.max_repairs} fixes), then ({edges})"
            )
            continue
        if step.kind == "tally":
            lines.append(f"- {step.id}: {_tally_said(step)}")
            continue
        if step.kind == "lock":
            lines.append(f"- {step.id}: {_lock_said(step)}")
            continue
        who = "whoever means a word differently" if step.to == CONTESTED else (step.to or "")
        turns = f", {step.rounds} rounds" if step.rounds > 1 else ""
        asks = "tells" if step.wait == "none" else "asks"
        if isinstance(step.next, str):
            lines.append(f"- {step.id}: {asks} {who}{turns}, then {step.next}")
        else:
            edges = ", ".join(f"{k}: {v}" for k, v in (step.next or {}).items())
            lines.append(f"- {step.id}: {asks} {who}{turns}, then by stance ({edges})")
    lines.append(f"up to {protocol.max_steps} steps")
    return "\n".join(lines)


def _edges_said(step: Step, words: dict[str, str]) -> str:
    """A code step's edges in plain words: ``new points: more, nothing new: ground``."""
    if isinstance(step.next, str):
        return f"then {step.next}"
    return ", ".join(f"{words.get(k, k)}: {v}" for k, v in (step.next or {}).items())


def _tally_said(step: Step) -> str:
    if step.of == "terms":
        return (
            f"sees whether a word is used in different senses, at most {step.max_rounds} "
            "times; "
            + _edges_said(step, {"contested": "yes", "clear": "no", "default": "otherwise"})
        )
    return (
        f"sees whether the last round added a point, up to {step.max_rounds} rounds; "
        + _edges_said(
            step,
            {
                "grew": "new points",
                "settled": "nothing new",
                "empty": "nobody gave any",
                "default": "otherwise",
            },
        )
    )


def _lock_said(step: Step) -> str:
    return "saves the shared summary; " + _edges_said(
        step, {"locked": "saved", "empty": "nothing to save", "default": "otherwise"}
    )


def edge_line(step: Step, stance: str | None, who: str) -> str | None:
    """One line saying which way a branching step went, or ``None`` for a plain
    edge. A step that asks nobody says where it went in its own post instead."""
    if not isinstance(step.next, dict) or step.kind in CODE_KINDS:
        return None
    target = step.edge(stance)
    said = {
        "accept": f"{who} accepted",
        "reject": f"{who} blocked",
        "silent": f"{who} did not answer",
    }.get(stance or "", f"{who} stated no stance")
    return f"{step.id}: {said}, on to {target}"


def spec_of(protocol: Protocol) -> dict[str, Any]:
    """The protocol as the YAML body of a ``protocols/<name>`` memory carries it."""
    data = protocol.model_dump(mode="json", exclude_none=True)
    data.pop("name", None)
    for step in data.get("steps", []):
        if step.get("wait") == "reply":
            step.pop("wait", None)
        if step.get("rounds") == 1:
            step.pop("rounds", None)
        if step.get("prompt") == "":
            step.pop("prompt", None)
        if step.get("kind") == "ask":
            step.pop("kind", None)
    return data


def room_protocol_names(room: str) -> list[str]:
    """The names of the protocols a room has written under ``protocols/``."""
    from app.services.filesystem import get_room_dir, list_memory_files, room_exists

    if not room_exists(room):
        return []
    return sorted(
        key.removeprefix(PROTOCOLS_PREFIX)
        for key, _meta, _content in list_memory_files(get_room_dir(room), prefix=PROTOCOLS_PREFIX)
    )


def catalogue(room: str) -> list[tuple[Protocol, Literal["builtin", "room"]]]:
    """Every flow a summon in ``room`` can name, as ``load_protocol`` resolves it.

    The room's own specs first (one that reshapes a built-in stands in for it),
    then the built-ins it leaves alone. A spec that does not parse is left out,
    as ``load_protocol`` would refuse to run it.
    """
    own: list[tuple[Protocol, Literal["builtin", "room"]]] = []
    for name in room_protocol_names(room):
        protocol = load_protocol(room, name)
        if protocol is not None:
            own.append((protocol, "room"))
    taken = {p.name for p, _ in own}
    rest: list[tuple[Protocol, Literal["builtin", "room"]]] = [
        (p, "builtin") for n in builtin_names() if n not in taken and (p := builtin(n)) is not None
    ]
    return own + rest


def builtin(name: str) -> Protocol | None:
    spec = BUILTIN_PROTOCOLS.get(name)
    return Protocol.model_validate(spec) if spec else None


def builtin_names() -> list[str]:
    return sorted(BUILTIN_PROTOCOLS)


def parse_protocol(name: str, body: str) -> Protocol:
    """A protocol from the YAML body of a ``protocols/<name>`` memory.

    The memory key is the name; a ``name`` inside the body is ignored so a
    copied spec cannot answer to a different name than the one it is filed
    under.
    """
    data = yaml.safe_load(body) or {}
    if not isinstance(data, dict):
        msg = f"protocol {name!r} is not a mapping"
        raise ValueError(msg)
    data["name"] = name
    return Protocol.model_validate(data)


def load_protocol(room: str, name: str) -> Protocol | None:
    """The room's ``protocols/<name>`` memory if it has one, else the built-in.

    A room's own spec wins, so a team can reshape a built-in under the same
    name. A spec that does not parse is logged and treated as absent rather
    than run half-read.
    """
    from app.services.filesystem import get_room_dir, read_memory_file, room_exists

    key = name.strip().lower()
    if not key:
        return None
    if room_exists(room):
        found = read_memory_file(get_room_dir(room), f"{PROTOCOLS_PREFIX}{key}")
        if found is not None:
            try:
                return parse_protocol(key, found[1])
            except (ValueError, yaml.YAMLError):
                logger.warning("room %s: protocols/%s does not parse", room, key, exc_info=True)
                return None
    return builtin(key)
