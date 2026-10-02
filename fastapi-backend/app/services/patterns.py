# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Patterns — design patterns as scenarios a room can be loaded from.

A **scenario** is a small room, ready to run: a cast, some context, a task and
the flow that sets them working (``scenarios/<pattern>/scenario.yaml`` in a
pattern pack). Loading one is the same writes any client can already make: the
room, its engines, memories, a task and, when asked, the summon that starts it.
This module is the scenario's shape, the checks that it fits, and the plan of
writes; ``routes/patterns.py`` makes them.

A pack is **data**: parsed with ``yaml.safe_load`` into strict models, never
imported or run. And the hub does not go and get one. A pack is a folder the
operator provides (``PATTERNS_DIR``); a caller names a pattern in it, never a
location. Only a trusted caller may send a scenario in the request itself
(``PATTERNS_ALLOW_INLINE``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.config import settings
from app.services.protocols import BUILTIN_PROTOCOLS, Protocol, builtin, parse_protocol

#: The conductor's handle in a loaded room; a scenario does not cast it.
CONDUCTOR = "conductor"

#: The seat the person loading a scenario takes.
HUMAN = "human"

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: What a member can be. ``human`` is the loader; the rest are engines the hub runs.
Kind = Literal["persona", "worker", "aligner", "synthesizer", "hello", "human"]

#: Kinds a flow can put a question to.
ASKABLE = frozenset({"persona", "worker", "human"})

#: Kinds allowed when the hub is set to personas only.
PERSONAS_ONLY_KINDS = frozenset({"persona", "human"})

#: What one batch write takes.
MAX_MEMORIES = 100


class PatternNotFound(LookupError):
    """No such pattern in the hub's pack."""


class PatternInvalid(ValueError):
    """A scenario that is malformed or does not fit, with every reason."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Context(_Strict):
    key: str
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _under_context(self) -> Context:
        if not self.key.startswith("context/") or not SLUG.match(self.key.removeprefix("context/")):
            msg = f"context key {self.key!r} must be context/<slug>"
            raise ValueError(msg)
        return self


class Member(_Strict):
    handle: str
    kind: Kind
    description: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def _shape(self) -> Member:
        if not SLUG.match(self.handle) or self.handle == CONDUCTOR:
            msg = f"handle {self.handle!r} must be a lowercase slug and not {CONDUCTOR!r}"
            raise ValueError(msg)
        if self.kind in ("persona", "worker") and not self.notes.strip():
            msg = f"{self.kind} {self.handle!r} needs notes: they are its character"
            raise ValueError(msg)
        if self.kind == HUMAN and self.notes:
            msg = f"human {self.handle!r} takes no notes"
            raise ValueError(msg)
        return self


class Task(_Strict):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""


class Summon(_Strict):
    flow: str
    members: list[str] = Field(min_length=1)
    ask: str = Field(min_length=1)


class Room(_Strict):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=500)


class Before(_Strict):
    """Where the run starts, said in a line and a sentence or two."""

    headline: str = Field(min_length=1, max_length=120)
    detail: str = Field("", max_length=300)


class After(_Strict):
    """What a reader wants to know at the end, so it can be restated as the run goes."""

    track: str = Field(min_length=1, max_length=500)


#: The parts of a run a guide step can point at.
GuideAt = Literal["before", "after", "members", "flow", "chat", "turn"]


class GuideStep(_Strict):
    at: GuideAt
    title: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=500)


class Scenario(_Strict):
    pattern: str
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=300)
    room: Room
    context: list[Context] = Field(default_factory=list)
    members: list[Member] = Field(min_length=1)
    task: Task
    summon: Summon | None = None
    #: A flow file beside the scenario, installed as protocols/<summon.flow>.
    flow_file: str | None = None
    #: How the run reads to someone watching it: where it starts, what the
    #: result is about, and a short walk through what is on screen. None of it
    #: is written to the room; a viewer reads it from the pattern.
    before: Before | None = None
    after: After | None = None
    guide: list[GuideStep] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _pattern_is_a_slug(self) -> Scenario:
        if not SLUG.match(self.pattern):
            msg = f"pattern {self.pattern!r} must be a lowercase slug"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _guide_points_at_what_exists(self) -> Scenario:
        if any(s.at == "turn" for s in self.guide) and not any(
            m.kind == HUMAN for m in self.members
        ):
            msg = "a guide step at 'turn' needs a person in the cast to take one"
            raise ValueError(msg)
        if any(s.at == "before" for s in self.guide) and self.before is None:
            msg = "a guide step at 'before' needs a before"
            raise ValueError(msg)
        if any(s.at == "after" for s in self.guide) and self.after is None:
            msg = "a guide step at 'after' needs an after"
            raise ValueError(msg)
        return self


@dataclass
class Loaded:
    """A scenario that fits, with the flow it runs when it has one."""

    scenario: Scenario
    #: The flow's YAML when the scenario brings its own.
    flow_body: str | None
    protocol: Protocol | None


# ── checking a scenario ──────────────────────────────────────────────────────


def parse(data: Any, flow_body: str | None = None, *, personas_only: bool | None = None) -> Loaded:
    """A scenario from its parsed YAML, checked as data and against the hub.

    The flow is parsed with the hub's own :class:`Protocol` model. That matters
    because the hub does not check a ``protocols/<name>`` memory when it is
    written: a bad flow is silently left out of the room's flows, so it has to
    be refused here, before anything is written.
    """
    try:
        scenario = Scenario.model_validate(data)
    except ValidationError as exc:
        raise PatternInvalid([_describe(e) for e in exc.errors()]) from exc
    only = settings.PATTERNS_PERSONAS_ONLY if personas_only is None else personas_only
    problems, protocol = _fit(scenario, flow_body, personas_only=only)
    if problems:
        raise PatternInvalid(problems)
    return Loaded(scenario=scenario, flow_body=flow_body, protocol=protocol)


def _describe(error: Any) -> str:
    where = ".".join(str(p) for p in error.get("loc", ()))
    return f"{where}: {error.get('msg', 'invalid')}" if where else str(error.get("msg"))


def _fit(
    scenario: Scenario, flow_body: str | None, *, personas_only: bool
) -> tuple[list[str], Protocol | None]:
    problems: list[str] = []
    handles = [m.handle for m in scenario.members]
    if len(set(handles)) != len(handles):
        problems.append("member handles must be distinct")
    if sum(m.kind == HUMAN for m in scenario.members) > 1:
        problems.append("at most one human seat: the person who loads it")
    if len({c.key for c in scenario.context}) != len(scenario.context):
        problems.append("context keys must be distinct")
    if personas_only:
        for m in scenario.members:
            if m.kind not in PERSONAS_ONLY_KINDS:
                problems.append(f"{m.handle!r} is a {m.kind}; this hub loads personas only")
    if bool(scenario.flow_file) != (flow_body is not None):
        problems.append(
            "flow_file is set but no flow came with it"
            if scenario.flow_file
            else "a flow came with the scenario but flow_file does not name it"
        )
    summon = scenario.summon
    if summon is None:
        if scenario.flow_file:
            problems.append("flow_file is set but there is no summon to run it")
        return problems, None

    protocol: Protocol | None = None
    if flow_body is not None:
        try:
            protocol = parse_protocol(summon.flow, flow_body)
        except (ValueError, yaml.YAMLError) as exc:
            problems.append(f"flow {scenario.flow_file}: {exc}")
    elif summon.flow in BUILTIN_PROTOCOLS:
        protocol = builtin(summon.flow)
    else:
        problems.append(
            f"summon.flow {summon.flow!r} is not built in "
            f"({', '.join(sorted(BUILTIN_PROTOCOLS))}) and no flow_file is given"
        )
    if protocol is None:
        return problems, None
    problems += _cast_fits(scenario, summon, protocol)
    return problems, protocol


def _cast_fits(scenario: Scenario, summon: Summon, protocol: Protocol) -> list[str]:
    problems: list[str] = []
    by_handle = {m.handle: m for m in scenario.members}
    unknown = [h for h in summon.members if h not in by_handle]
    if unknown:
        return [f"summon names members the scenario does not cast: {unknown}"]
    if len(set(summon.members)) != len(summon.members):
        problems.append("summon members must be distinct")
    if len(summon.members) < len(protocol.roles):
        problems.append(
            f"flow {summon.flow!r} has roles {protocol.roles}; the summon names too few"
        )
        return problems
    for role, handle in zip(protocol.roles, summon.members, strict=False):
        if by_handle[handle].kind not in ASKABLE:
            problems.append(f"role {role!r} is bound to {handle!r}, a {by_handle[handle].kind}")
    for handle in summon.members:
        if by_handle[handle].kind not in ASKABLE:
            problems.append(f"{handle!r} is a {by_handle[handle].kind}, which a flow cannot ask")
    held = set(summon.members[: len(protocol.roles)])
    if any(s.to == "workers" for s in protocol.steps) and held >= set(summon.members):
        problems.append(f"flow {summon.flow!r} asks workers, but every named member holds a role")
    return problems


# ── the pack ─────────────────────────────────────────────────────────────────


def pack_dir() -> Path | None:
    """The operator's pack, or ``None`` when the hub offers none."""
    raw = settings.PATTERNS_DIR.strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if (path / "scenarios").is_dir() else None


def pack_names() -> list[str]:
    root = pack_dir()
    if root is None:
        return []
    return sorted(p.parent.name for p in (root / "scenarios").glob("*/scenario.yaml"))


def read_pack(name: str) -> Loaded:
    """The pattern called ``name`` in the operator's pack.

    ``name`` is checked as a slug before it touches the filesystem, and a flow
    file must resolve inside the scenario's own folder, so neither can reach
    outside the pack.
    """
    root = pack_dir()
    if root is None or not SLUG.match(name):
        raise PatternNotFound(name)
    folder = root / "scenarios" / name
    path = folder / "scenario.yaml"
    if not path.is_file():
        raise PatternNotFound(name)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PatternInvalid([f"scenario.yaml cannot be read: {exc}"]) from exc
    if isinstance(data, dict) and data.get("pattern") != name:
        raise PatternInvalid([f"pattern {data.get('pattern')!r} must match its folder {name!r}"])
    flow_body = None
    flow_file = data.get("flow_file") if isinstance(data, dict) else None
    if isinstance(flow_file, str):
        flow_path = (folder / flow_file).resolve()
        if folder.resolve() not in flow_path.parents or not flow_path.is_file():
            raise PatternInvalid(
                [f"flow_file {flow_file!r} is not a file in the scenario's folder"]
            )
        flow_body = flow_path.read_text(encoding="utf-8")
    return parse(data, flow_body)


def read_pack_all() -> tuple[list[Loaded], dict[str, str]]:
    """Every scenario in the pack that loads, and why each other one does not."""
    loaded: list[Loaded] = []
    skipped: dict[str, str] = {}
    for name in pack_names():
        try:
            loaded.append(read_pack(name))
        except (PatternInvalid, PatternNotFound) as exc:
            skipped[name] = str(exc)
    return loaded, skipped


# ── the plan ─────────────────────────────────────────────────────────────────


@dataclass
class Plan:
    """What loading a scenario writes, worked out before anything is written."""

    loaded: Loaded
    #: ``(handle, kind, description)`` for every engine to register.
    engines: list[tuple[str, str, str]]
    #: Memory items (key, value, embed), in the order they are written.
    memories: list[dict[str, Any]]
    #: The summon text, with the loader's own handle in the human seat.
    summon: str | None
    #: The handles a flow will name, in the order the summon names them.
    cast: list[str]


def build_plan(loaded: Loaded, me: str) -> Plan:
    """The writes that load ``loaded`` for ``me``."""
    scenario = loaded.scenario
    seat = {m.handle: (me if m.kind == HUMAN else m.handle) for m in scenario.members}
    engines: list[tuple[str, str, str]] = []
    if scenario.summon is not None:
        engines.append((CONDUCTOR, "conductor", f"Runs the {scenario.summon.flow} flow."))
    engines += [(m.handle, m.kind, m.description) for m in scenario.members if m.kind != HUMAN]

    memories: list[dict[str, Any]] = [
        {"key": c.key, "value": c.text.strip(), "embed": True} for c in scenario.context
    ]
    memories += [
        {"key": f"agents/{m.handle}/notes", "value": m.notes.strip(), "embed": False}
        for m in scenario.members
        if m.notes.strip()
    ]
    summon = None
    cast: list[str] = []
    if scenario.summon is not None:
        if loaded.flow_body is not None:
            memories.append(
                {
                    "key": f"protocols/{scenario.summon.flow}",
                    "value": loaded.flow_body,
                    "embed": False,
                }
            )
        cast = [seat[h] for h in scenario.summon.members]
        names = " ".join(f"@{h}" for h in cast)
        summon = f"@{CONDUCTOR} {scenario.summon.flow} {names}: {scenario.summon.ask}"
    if len(memories) > MAX_MEMORIES:
        raise PatternInvalid([f"{len(memories)} memories to write; the limit is {MAX_MEMORIES}"])
    return Plan(loaded=loaded, engines=engines, memories=memories, summon=summon, cast=cast)
