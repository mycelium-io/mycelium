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

#: The stances an edge can branch on, plus the two fallbacks.
EDGE_KEYS = frozenset({"accept", "reject", "silent", "default"})

Outcome = Literal["resolved", "rejected"]


class Step(BaseModel):
    """One step: who is asked what, and where the reply leads."""

    id: str = Field(..., min_length=1)
    to: str | None = Field(
        None, description="A role, or each / all / workers. Absent on an end step."
    )
    prompt: str = ""
    wait: Literal["reply", "none"] = "reply"
    rounds: int = Field(1, ge=1, description="How many times an each/all step repeats.")
    next: str | dict[str, str] | None = Field(
        None,
        description=(
            "The step after this one: a step id, or a map of accept / reject / "
            "silent / default to step ids."
        ),
    )
    end: Outcome | None = Field(None, description="Set on a terminal step: how the run ends.")

    @model_validator(mode="after")
    def _terminal_or_addressed(self) -> Step:
        if self.end is not None:
            if self.to is not None or self.next is not None:
                msg = f"step {self.id!r} ends the run and cannot also address or continue"
                raise ValueError(msg)
            return self
        if not self.to:
            msg = f"step {self.id!r} addresses nobody and ends nothing"
            raise ValueError(msg)
        if self.next is None:
            msg = f"step {self.id!r} names no next step"
            raise ValueError(msg)
        if isinstance(self.next, dict):
            unknown = set(self.next) - EDGE_KEYS
            if unknown:
                msg = (
                    f"step {self.id!r} branches on {sorted(unknown)}; edges are {sorted(EDGE_KEYS)}"
                )
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
        if set(clean) & GROUP_TARGETS:
            msg = f"a role cannot be named {sorted(set(clean) & GROUP_TARGETS)}"
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
            if step.to is not None and step.to not in GROUP_TARGETS and step.to not in self.roles:
                msg = f"step {step.id!r} addresses {step.to!r}, which is neither a role nor a group"
                raise ValueError(msg)
            targets = (
                [step.next] if isinstance(step.next, str) else list((step.next or {}).values())
            )
            for target in targets:
                if target not in known:
                    msg = f"step {step.id!r} continues to {target!r}, which is not a step"
                    raise ValueError(msg)
        if not any(s.end for s in self.steps):
            msg = "a protocol needs at least one end step"
            raise ValueError(msg)
        return self

    @property
    def first(self) -> Step:
        return self.steps[0]

    def step(self, step_id: str) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)


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
}


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
