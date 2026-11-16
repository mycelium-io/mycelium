# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The kinds of memory a room keeps, and what a write from the memory route may do.

A key's kind is the first in :data:`KINDS` whose pattern matches it. A write
from the memory route (the app's editor, ``memory set``, an agent, a scenario)
is checked against its kind before anything is saved (:func:`check`), and a
refusal says why with a stable code (``memory.read_only``, ``memory.yaml_invalid``
and the rest), so a person and an agent both see what to do instead. The hub's
own processes write through their own routes and own what a kind keeps from
people: the conductor its run records, a lease its claim fields, the upload
route an upload's file.

The table is a copy of ``contracts/memory-kinds.json``; the frontend and the
CLI hold their halves of it, and each side's tests assert against the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

from app.services.filesystem import MANAGED_META

Edit = Literal["body", "field", "none"]


@dataclass(frozen=True)
class Kind:
    id: str
    patterns: tuple[str, ...]
    edit: Edit
    #: The frontmatter field a ``field`` kind's body is drawn from.
    source: str | None = None
    #: Frontmatter a person may not change.
    fixed: tuple[str, ...] = ()
    #: What's run on the written content.
    checks: tuple[str, ...] = ()
    #: What a refused write to an ``edit: none`` kind says.
    says: str | None = None
    _res: tuple[re.Pattern[str], ...] = field(default=(), repr=False, compare=False)

    def matches(self, key: str) -> bool:
        return any(r.fullmatch(key) for r in self._res)


def _compile(pattern: str) -> re.Pattern[str]:
    """``*`` is one part of a key, ``**`` any number of parts."""
    parts = (re.escape(p) for p in pattern.split("**"))
    return re.compile(".+".join(p.replace(r"\*", "[^/]+") for p in parts))


def _kind(id: str, *patterns: str, **kw: Any) -> Kind:
    return Kind(id, patterns, _res=tuple(_compile(p) for p in patterns), **kw)


#: Each claim field a lease owns on a task row (``services/fields.py``).
CLAIM_FIELDS = (
    "assignment",
    "owner",
    "claimed_at",
    "ttl_minutes",
    "assignment_note",
    "assignment_note_by",
)

KINDS: tuple[Kind, ...] = (
    _kind(
        "upload",
        "uploads/**",
        edit="none",
        says="An upload is its file, and can't be edited. Upload the file again to replace it.",
    ),
    _kind("agent", "agents/*", edit="body", checks=("yaml", "agent_manifest")),
    _kind("protocol", "protocols/*", edit="body", checks=("yaml", "protocol")),
    _kind("setting", "settings/*", edit="body", checks=("setting",)),
    _kind("skill", "skills/*", edit="body", checks=("skill_description",)),
    _kind("thread", "threads/*", edit="body", fixed=("from",)),
    _kind(
        "task", "work/**", "decisions/**", "status/**", "failed/**", edit="body", fixed=CLAIM_FIELDS
    ),
    _kind("summary", "context/summary/**", edit="field", source="contract", checks=("summary",)),
    _kind("decision", "context/decision/**", edit="field", source="decision", checks=("decision",)),
    _kind("synthesis", "context/synthesis", edit="body", fixed=("synthesized_through",)),
    _kind(
        "standing",
        "context/standing",
        edit="none",
        says="Mycelium writes this after every step of a flow, so it can't be edited.",
    ),
    _kind(
        "episode_record",
        "log/episodes/*",
        edit="none",
        says="This is the record of a flow's run, written as it runs, so it can't be edited.",
    ),
    _kind("memory", "**", edit="body"),
)

#: Every refusal's code and the status it's sent with.
CODES: dict[str, int] = {
    "memory.stale_base": 409,
    "memory.store_field": 422,
    "memory.fixed_field": 422,
    "memory.claim_field": 422,
    "memory.read_only": 409,
    "memory.rendered_body": 409,
    "memory.yaml_invalid": 422,
    "memory.schema_invalid": 422,
    "memory.not_owner": 403,
    "memory.setting_unknown": 422,
    "memory.setting_invalid": 422,
}

#: The most a skill's one-line description may hold (``SkillCreate``).
SKILL_DESCRIPTION_MAX = 512


class Refused(Exception):
    """A write the table refuses: its code, the sentence to show, and anything more."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.status = CODES[code]
        self.message = message
        self.extra = extra

    def detail(self, key: str) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "key": key, **self.extra}


def kind_of(key: str) -> Kind:
    return next(k for k in KINDS if k.matches(key))


def check(
    key: str,
    body: str,
    meta: dict[str, Any] | None,
    existing: tuple[dict[str, Any], str] | None,
) -> str | None:
    """Refuse a write from the memory route that ``key``'s kind doesn't allow.

    ``body`` and ``meta`` are what the write says; ``existing`` is the memory
    on disk (frontmatter and body), if there is one. Returns the body to save
    in place of ``body`` when the kind draws it from a field, else ``None``.
    """
    kind = kind_of(key)
    meta = meta or {}
    old_meta, old_body = existing if existing else ({}, None)
    if kind.edit == "none":
        raise Refused("memory.read_only", kind.says or f"{key} can't be edited.")
    _check_fields(key, kind, meta, old_meta)
    for name in kind.checks:
        _CHECKS[name](key, body, meta)
    if kind.edit == "field" and kind.source:
        return _drawn_body(key, kind, body, meta, old_meta, old_body)
    return None


def _changes(meta: dict[str, Any], old_meta: dict[str, Any], name: str) -> bool:
    """Whether this write sets ``name`` to something other than what's stored.
    Sending back the value a memory already has changes nothing, so a client
    that writes back what it read is never refused for it."""
    return name in meta and meta[name] != old_meta.get(name)


def _check_fields(key: str, kind: Kind, meta: dict[str, Any], old_meta: dict[str, Any]) -> None:
    stored = sorted(n for n in MANAGED_META if _changes(meta, old_meta, n))
    if stored:
        raise Refused(
            "memory.store_field",
            f"{', '.join(stored)} {'is' if len(stored) == 1 else 'are'} kept by Mycelium "
            f"and can't be written. Leave {'it' if len(stored) == 1 else 'them'} out.",
            fields=stored,
        )
    fixed = [n for n in kind.fixed if _changes(meta, old_meta, n)]
    if fixed and kind.id == "task":
        raise Refused(
            "memory.claim_field",
            "Who holds a task is changed by claiming it: use `mycelium board claim`, "
            "`release` or `assign`, or the board's buttons.",
            fields=fixed,
        )
    if fixed:
        raise Refused(
            "memory.fixed_field",
            f"{', '.join(fixed)} {'is' if len(fixed) == 1 else 'are'} set by Mycelium "
            f"on {key} and can't be changed.",
            fields=fixed,
        )


def _drawn_body(
    key: str,
    kind: Kind,
    body: str,
    meta: dict[str, Any],
    old_meta: dict[str, Any],
    old_body: str | None,
) -> str | None:
    """A summary's or a decision's body is drawn from its field: a write that
    changes the field gets the body redrawn, and one that changes only the
    body is refused, since the next redraw would lose it."""
    assert kind.source is not None
    if _changes(meta, old_meta, kind.source):
        return _RENDER[kind.id](meta[kind.source])
    if old_body is None or body.strip() != old_body.strip():
        what = "summary" if kind.id == "summary" else "decision"
        raise Refused(
            "memory.rendered_body",
            f"This text is made from the {what} in its `{kind.source}` field. "
            f"Edit the {what} there and the text follows.",
        )
    return None


# ── what's checked on the written content ────────────────────────────────────


def _yaml(key: str, body: str, _meta: dict[str, Any]) -> None:
    try:
        yaml.safe_load(body)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise Refused(
            "memory.yaml_invalid",
            f"{key} has to be YAML, and this doesn't parse{where}: {getattr(e, 'problem', e)}.",
        ) from e


def _agent_manifest(key: str, body: str, _meta: dict[str, Any]) -> None:
    data = yaml.safe_load(body) or {}
    if not isinstance(data, dict):
        raise Refused("memory.schema_invalid", f"{key} has to be a YAML mapping of fields.")
    lists = ("allow_from", "a2a_skills")
    texts = ("adapter", "owner", "description", "framework", "runner")
    for name in lists:
        if data.get(name) is not None and not isinstance(data[name], list):
            raise Refused("memory.schema_invalid", f"{key}: `{name}` has to be a list.")
    for name in texts:
        if data.get(name) is not None and not isinstance(data[name], str):
            raise Refused("memory.schema_invalid", f"{key}: `{name}` has to be text.")


def _protocol(key: str, body: str, _meta: dict[str, Any]) -> None:
    from pydantic import ValidationError

    from app.services.protocols import parse_protocol

    try:
        parse_protocol(key.split("/", 1)[1], body)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise Refused(
            "memory.schema_invalid",
            f"{key} isn't a flow Mycelium can run: {where + ': ' if where else ''}{first['msg']}.",
        ) from e
    except ValueError as e:
        raise Refused("memory.schema_invalid", f"{key} isn't a flow Mycelium can run: {e}.") from e


def _setting(_key: str, _body: str, _meta: dict[str, Any]) -> None:
    # The settings table's own check runs in the upsert for every writer (it
    # also normalizes the value), and its refusal takes the setting codes.
    return


def _skill_description(key: str, _body: str, meta: dict[str, Any]) -> None:
    said = meta.get("description")
    if said is not None and (not isinstance(said, str) or len(said) > SKILL_DESCRIPTION_MAX):
        raise Refused(
            "memory.schema_invalid",
            f"{key}: `description` is one line of text, at most {SKILL_DESCRIPTION_MAX} characters.",
        )


def _summary(key: str, _body: str, meta: dict[str, Any]) -> None:
    if "contract" in meta:
        _RENDER["summary"](meta["contract"], key=key)


def _decision(key: str, _body: str, meta: dict[str, Any]) -> None:
    if "decision" in meta:
        _RENDER["decision"](meta["decision"], key=key)


_CHECKS = {
    "yaml": _yaml,
    "agent_manifest": _agent_manifest,
    "protocol": _protocol,
    "setting": _setting,
    "skill_description": _skill_description,
    "summary": _summary,
    "decision": _decision,
}


# ── a body drawn from its field ──────────────────────────────────────────────


def render_summary(made: Any, *, key: str = "the summary") -> str:
    """The summary's text from its ``contract``, or a refusal when it can't be drawn."""
    from app.services import frame

    if not isinstance(made, dict):
        raise Refused("memory.schema_invalid", f"{key}: `contract` has to be a mapping.")
    try:
        return frame.render(made)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise Refused(
            "memory.schema_invalid",
            f"{key}: `contract` is missing or mistyping a part the summary is drawn from ({e}).",
        ) from e


def render_decision(decided: Any, *, key: str = "the decision") -> str:
    """The decision's text from its ``decision`` field, or a refusal."""
    if not isinstance(decided, dict) or not isinstance(decided.get("text"), str):
        raise Refused(
            "memory.schema_invalid",
            f"{key}: `decision` has to be a mapping with the decision as `text`.",
        )
    pick = decided.get("pick")
    lines = ["# Decision", "", f"Going with {pick}: {decided['text']}" if pick else decided["text"]]
    views = [v for v in decided.get("views") or [] if isinstance(v, str)]
    if views:
        lines += ["", "## How each member sees it", "", *(f"- {v}" for v in views)]
    return "\n".join(lines) + "\n"


_RENDER = {"summary": render_summary, "decision": render_decision}
