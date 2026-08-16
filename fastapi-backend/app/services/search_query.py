# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The command-style search grammar.

One line of text carries both the words to look for and the scope to look in::

    #atlas @avery memory: postgres

    ├─────┤ ├────┤ ├─────┤ ├──────┤
    room    actor   type    free text

Tokens
------
``#<room>``      scope to a room; repeatable, and rooms union.
``@<handle>``    scope to an actor — the author of a memory or message, a
                 participant in an episode, the agent itself. Repeatable.
``<type>:``      restrict the result types. One of ``memory``, ``episode``,
                 ``message``, ``room``, ``agent`` (plurals and ``msg`` accepted).
                 Text after the colon joins the free text, so a half-typed
                 ``memory:postg`` narrows as it is typed rather than matching
                 nothing until the space.
``kind:<value>`` filter by whatever "kind" means for a type: an episode's
                 outcome, a message's type, an agent's engine kind, a memory's
                 namespace. Repeatable. It fails closed — a type with no kind at
                 all (a room) drops out rather than matching everything.

Anything else is free text. A token whose prefix isn't a known type is free text
too, so a memory key like ``log/episodes/a1b2`` or a URL survives the parse
intact.

The parse is server-side and echoed back on the response, so the UI draws its
scope chips from the same interpretation the search ran under — there is one
grammar, not a client copy that can drift from it.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Result types, in the order a caller listing them should show them.
RESULT_TYPES: tuple[str, ...] = ("room", "agent", "episode", "memory", "message")

#: Accepted spellings of each type token, mapped to the canonical type.
TYPE_TOKENS: dict[str, str] = {
    "memory": "memory",
    "memories": "memory",
    "mem": "memory",
    "episode": "episode",
    "episodes": "episode",
    "ep": "episode",
    "message": "message",
    "messages": "message",
    "msg": "message",
    "room": "room",
    "rooms": "room",
    "agent": "agent",
    "agents": "agent",
}

_KIND_TOKEN = "kind"


@dataclass(frozen=True)
class ParsedQuery:
    """A raw query string, split into scope and words."""

    #: The free text, tokens stripped, lowercased and whitespace-collapsed.
    text: str = ""
    #: Room names to search within; empty means every room.
    rooms: tuple[str, ...] = ()
    #: Actor handles to scope by; empty means every actor.
    actors: tuple[str, ...] = ()
    #: Result types to keep; empty means every type.
    types: tuple[str, ...] = ()
    #: L9 kind/subkind values to keep; empty means every kind.
    kinds: tuple[str, ...] = ()

    @property
    def terms(self) -> list[str]:
        """The free text as match terms."""
        return self.text.split()

    @property
    def is_empty(self) -> bool:
        """True when there is nothing at all to act on — not even a scope."""
        return not (self.text or self.rooms or self.actors or self.types or self.kinds)

    def wants(self, result_type: str) -> bool:
        """True when ``result_type`` survives the type filter."""
        return not self.types or result_type in self.types


def _clean(value: str) -> str:
    return value.strip().lstrip("@#").lower()


def _dedup(values: list[str]) -> tuple[str, ...]:
    """Order-preserving dedup — a repeated token is a typo, not a weight."""
    return tuple(dict.fromkeys(v for v in values if v))


def parse(raw: str) -> ParsedQuery:
    """Split ``raw`` into its scope tokens and free text."""
    rooms: list[str] = []
    actors: list[str] = []
    types: list[str] = []
    kinds: list[str] = []
    words: list[str] = []

    for token in raw.split():
        if token.startswith("#") and len(token) > 1:
            rooms.append(_clean(token))
            continue
        if token.startswith("@") and len(token) > 1:
            actors.append(_clean(token))
            continue
        prefix, sep, rest = token.partition(":")
        if sep:
            lowered = prefix.lower()
            if lowered == _KIND_TOKEN:
                if rest:
                    kinds.append(_clean(rest))
                continue
            if lowered in TYPE_TOKENS:
                types.append(TYPE_TOKENS[lowered])
                if rest:
                    words.append(rest.lower())
                continue
        words.append(token.lower())

    return ParsedQuery(
        text=" ".join(w for w in words if w),
        rooms=_dedup(rooms),
        actors=_dedup(actors),
        types=_dedup(types),
        kinds=_dedup(kinds),
    )
