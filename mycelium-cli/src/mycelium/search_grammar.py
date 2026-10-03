# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The message search grammar, as the CLI needs to know it.

The hub parses and runs a query (``GET /rooms/{room}/messages/search``); this
copy exists for the two things the CLI does with one before it is sent:
building a query out of flags (``mycelium room search --from avery``), and
checking the queries written in the docs, skills and prompts
(``cli_prose``), so a field the hub does not answer can't be taught to an
agent. ``contracts/message-search.json`` freezes the words both copies share;
``tests/test_search_grammar.py`` asserts this one against it.

A ``name:value`` the hub doesn't know is free text there, not an error — a URL
has a colon in it. Written in a query on purpose it is almost always a field
spelled wrong, which the hub would then quietly search for as words; so here
it is a problem.
"""

from __future__ import annotations

import re

FIELDS: tuple[str, ...] = (
    "from",
    "to",
    "mentions",
    "task",
    "in",
    "type",
    "kind",
    "status",
    "stance",
    "step",
    "is",
    "has",
    "day",
    "thread",
)

ALIASES: dict[str, str] = {
    "sender": "from",
    "by": "from",
    "author": "from",
    "recipient": "to",
    "mention": "mentions",
    "row": "task",
    "episode": "thread",
    "date": "day",
}

AT_FIELD = "from"

TIME_KEYS: dict[str, str] = {
    "after": "after",
    "since": "after",
    "before": "before",
    "until": "before",
    "on": "on",
}

SORTS: tuple[str, ...] = ("newest", "oldest", "relevance")

CLOSED_VALUES: dict[str, tuple[str, ...]] = {
    "in": ("channel", "thread"),
    "is": ("edited", "conductor"),
    "has": ("mention", "link", "memory", "code", "scores"),
    "stance": ("accept", "reject"),
}

_TOKEN = re.compile(r'(-?)(?:([A-Za-z][\w-]*):)?("([^"]*)"?|\S+)')
_AGE = re.compile(r"^\d+\s*(m|min|h|d|w)$", re.IGNORECASE)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ][\d:.]+(Z|[+-]\d{2}:?\d{2})?)?$")
#: A value standing in for one: ``<handle>``, ``{room}``, ``$WHO``, ``...``.
_PLACEHOLDER = re.compile(r"^(<.*>|\{.*\}|\$.*|\.\.\.|…)$")


def canonical(name: str) -> str | None:
    """The field ``name`` spells, or None when it is not one."""
    name = name.lower()
    if name in FIELDS:
        return name
    return ALIASES.get(name)


def is_time(value: str) -> bool:
    """Whether ``value`` reads as a time the hub accepts."""
    text = value.strip().lower()
    return bool(_AGE.match(text) or text in ("today", "yesterday") or _DATE.match(value.strip()))


def problems(query: str) -> list[str]:
    """Everything in ``query`` the hub would not read the way it looks.

    A field it does not have, a value outside a closed field's set, a time it
    cannot parse, a sort that does not exist. Placeholders stand for values
    and pass.
    """
    found: list[str] = []
    for m in _TOKEN.finditer(query):
        name = m.group(2)
        if not name:
            continue
        value = m.group(4) if m.group(4) is not None else m.group(3)
        token = m.group(0)
        if value.startswith("//"):
            continue  # a URL's scheme, not a field
        if _PLACEHOLDER.match(value):
            if not (canonical(name) or name.lower() in TIME_KEYS or name.lower() == "sort"):
                found.append(f"{token}: no field {name!r}")
            continue
        lowered = name.lower()
        if lowered in TIME_KEYS:
            if not is_time(value):
                found.append(f"{token}: not a time (an ISO date, an age like 2h, today)")
        elif lowered == "sort":
            if value.lower() not in SORTS:
                found.append(f"{token}: sort is one of {', '.join(SORTS)}")
        elif (field := canonical(name)) is None:
            found.append(f"{token}: no field {name!r} (fields: {', '.join(FIELDS)})")
        elif field in CLOSED_VALUES and value.lower() not in CLOSED_VALUES[field]:
            found.append(f"{token}: {field} is one of {', '.join(CLOSED_VALUES[field])}")
    return found


def clause(field: str, value: str, *, negate: bool = False) -> str:
    """One ``field:value`` token, quoted when the value has a space in it."""
    shown = f'"{value}"' if any(c.isspace() for c in value) else value
    return f"{'-' if negate else ''}{field}:{shown}"
