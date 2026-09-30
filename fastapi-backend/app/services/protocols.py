# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Protocols — the shapes a conductor runs a thread through.

A protocol is a small graph of **steps**. Each step puts a prompt to one
member, to each in turn, or to several at once, waits for what comes back,
and names the step after it — by one edge, or by one edge per stance the
reply took. The graph is data, not cognition: the conductor walks it in code
and the only judgment in a run is inside the members it addresses.

Three protocols ship built in, and a room can add its own or override one
of these by writing a ``protocols/<name>`` memory whose body is the same YAML
(:func:`load_protocol`). Like skills, a protocol is a memory promoted: no
separate store, and one is readable as a memory too.

Step targets: a **role** the summon bound (``@conductor gated @a @b`` binds
``a`` and ``b`` to the protocol's roles in order), ``each`` (every member,
one at a time), ``all`` (every member, at once), or ``workers`` (every
member not bound to a named role, at once).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

#: The memory namespace protocols live in.
PROTOCOLS_PREFIX = "protocols/"

#: What a step may be put to besides a role.
GROUP_TARGETS = frozenset({"each", "all", "workers"})

#: The one member the latest ``select`` step found least happy with its pick.
BOTTLENECK = "bottleneck"

#: The stances an edge can branch on, plus the two fallbacks.
EDGE_KEYS = frozenset({"accept", "reject", "silent", "default"})

#: How a ``select`` step's pick went: everyone's on board, someone can fix it,
#: or a fix can't help.
SELECT_EDGES = frozenset({"feasible", "infeasible", "stuck", "default"})

#: ``converged`` is the one end that compiles work: an agreement a ``select``
#: step certified. Every other flow ends ``resolved`` or ``rejected``.
Outcome = Literal["resolved", "rejected", "converged"]

#: The outcomes that read as success wherever a run's end is drawn.
SUCCESS = frozenset({"resolved", "converged"})

DEFAULT_THRESHOLD = 0.7
DEFAULT_MAX_REPAIRS = 2


class Step(BaseModel):
    """One step: who is asked what, and where the reply leads.

    A ``select`` step asks nobody: it picks among the options the members
    suggested, by the ratings they gave (:mod:`app.services.select`), and
    branches on whether everyone is on board.
    """

    id: str = Field(..., min_length=1)
    kind: Literal["ask", "select"] = "ask"
    to: str | None = Field(
        None,
        description="A role, or each / all / workers / bottleneck. Absent on an end or select step.",
    )
    prompt: str = ""
    wait: Literal["reply", "none"] = "reply"
    rounds: int = Field(1, ge=1, description="How many times an each/all step repeats.")
    collect: Literal["options", "scores"] | None = Field(
        None,
        description=(
            "What the replies add to the run: each reply becomes an option, or "
            "each reply's ratings are recorded."
        ),
    )
    require: Literal["stance", "scores"] | None = Field(
        None,
        description=(
            "What every reply must carry. A reply without it is asked once more; "
            "an unmarked stance after that counts as reject."
        ),
    )
    threshold: float | None = Field(
        None, ge=0, le=1, description="A select step's bar, 0-1 (0.7 = everyone rates it 70+)."
    )
    max_repairs: int | None = Field(
        None, ge=0, description="How many fixes a select step sends for before it is stuck."
    )
    next: str | dict[str, str] | None = Field(
        None,
        description=(
            "The step after this one: a step id, or a map of accept / reject / "
            "silent / default (a select: feasible / infeasible / stuck / default) "
            "to step ids."
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
        if self.kind == "select":
            return self._a_select()
        if self.threshold is not None or self.max_repairs is not None:
            msg = f"step {self.id!r}: threshold and max_repairs belong to a select step"
            raise ValueError(msg)
        if not self.to:
            msg = f"step {self.id!r} addresses nobody and ends nothing"
            raise ValueError(msg)
        return self._branches(EDGE_KEYS)

    def _a_select(self) -> Step:
        if self.to is not None or self.prompt or self.collect or self.require:
            msg = f"select step {self.id!r} asks nobody: it takes no to, prompt, collect or require"
            raise ValueError(msg)
        if not isinstance(self.next, dict):
            msg = f"select step {self.id!r} branches by map: {sorted(SELECT_EDGES)}"
            raise ValueError(msg)
        # Written out, so the flow as the app reads it carries the bar.
        if self.threshold is None:
            self.threshold = DEFAULT_THRESHOLD
        if self.max_repairs is None:
            self.max_repairs = DEFAULT_MAX_REPAIRS
        return self._branches(SELECT_EDGES)

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
        reserved = set(clean) & (GROUP_TARGETS | {BOTTLENECK})
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
                and step.to != BOTTLENECK
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
        self._bottleneck_follows_a_select()
        self._converged_is_certified()
        return self

    def _bottleneck_follows_a_select(self) -> None:
        """``to: bottleneck`` names whoever the latest pick found least happy, so
        every path from the first step to it has to pass a ``select`` first."""
        by_id = {s.id: s for s in self.steps}
        seen: set[str] = set()
        frontier = [self.first.id]
        while frontier:
            step = by_id[frontier.pop()]
            if step.id in seen:
                continue
            seen.add(step.id)
            if step.to == BOTTLENECK:
                msg = (
                    f"step {step.id!r} asks the bottleneck, but a path reaches it before any select"
                )
                raise ValueError(msg)
            if step.kind == "select":
                continue  # past a pick, a bottleneck is defined
            frontier.extend(_targets_of(step))

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
                "prompt": (
                    "{ask}\n\nSuggest the one option you think best serves your role for "
                    "{task}, in one or two sentences. Don't hedge or pre-compromise."
                ),
                "next": "score",
            },
            {
                "id": "score",
                "to": "all",
                "collect": "scores",
                "prompt": (
                    "The options for {task}:\n\n{options}\n\nRate each one 0-100 for your "
                    "own role: 0 means unacceptable, 100 means ideal. Give one line on why "
                    "for each, then end with [[mycelium: A=.. B=..]]."
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
                "prompt": (
                    "{scores}\n\n{shortfall}. Suggest ONE new option you'd rate highly that "
                    "keeps what the others rated high. Say what you changed and why it "
                    "should work for them."
                ),
                "next": "rescore",
            },
            {
                "id": "rescore",
                "to": "all",
                "collect": "scores",
                "prompt": (
                    "A new option:\n\n{new_options}\n\nRate it 0-100 for your role, with "
                    "one line on why, then end with [[mycelium: {new_labels}]]."
                ),
                "next": "pick",
            },
            {"id": "agreed", "end": "converged"},
            {"id": "no_deal", "end": "rejected"},
        ],
    },
    # IoC L9's Accord, cut down: everyone frames the task, one lead merges, and
    # the frame locks once nobody objects.
    "accord": {
        "name": "accord",
        "description": (
            "Get on the same page. Agree what the task is, what's out of scope, what "
            "done means and what the key words mean, before work starts."
        ),
        "roles": ["lead"],
        # Frame, merge, lock, a re-ask, then one full revision with its re-ask.
        "max_steps": 8,
        "steps": [
            {
                "id": "frame",
                "to": "all",
                "prompt": (
                    "Before we start on {task}: in a few lines, what is it asking, what's "
                    "out of scope, and what does done look like? Name any word you're "
                    "using in a specific sense and say what you mean by it."
                ),
                "next": "merge",
            },
            {
                "id": "merge",
                "to": "lead",
                "prompt": (
                    "Everyone's take:\n\n{replies}\n\nWrite ONE shared summary: Objective, "
                    "Out of scope, Done when, Key words (word: meaning), Who checks what. "
                    "Name anything you couldn't reconcile instead of papering over it."
                ),
                "next": "lock",
            },
            {
                "id": "lock",
                "to": "all",
                "require": "stance",
                "prompt": (
                    "The shared summary:\n\n{reply}\n\nCan you work to this? End with "
                    "[[mycelium: stance=accept]], or [[mycelium: stance=reject]] and the "
                    "one change you need."
                ),
                # Only real silence is no objection: an unmarked reply was asked
                # again, and still unmarked it counts as reject.
                "next": {
                    "accept": "locked",
                    "reject": "merge",
                    "silent": "merge",
                    "default": "locked",
                },
            },
            {"id": "locked", "end": "resolved"},
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
        who = step.to or ""
        turns = f", {step.rounds} rounds" if step.rounds > 1 else ""
        asks = "tells" if step.wait == "none" else "asks"
        if isinstance(step.next, str):
            lines.append(f"- {step.id}: {asks} {who}{turns}, then {step.next}")
        else:
            edges = ", ".join(f"{k}: {v}" for k, v in (step.next or {}).items())
            lines.append(f"- {step.id}: {asks} {who}{turns}, then by stance ({edges})")
    lines.append(f"up to {protocol.max_steps} steps")
    return "\n".join(lines)


def edge_line(step: Step, stance: str | None, who: str) -> str | None:
    """One line saying which way a branching step went, or ``None`` for a plain
    edge. A select step says where it went in its scorecard instead."""
    if not isinstance(step.next, dict) or step.kind == "select":
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
