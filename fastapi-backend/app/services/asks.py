# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Whether a message asks an agent for something, and why: the one rule.

Three things act on it. The herdr doorbell queues a wake for an agent a
message asked (``persister`` → ``room_channels.ring_asked``), ``await`` hands
it over as the agent's turn (``participate``), and the wake digest lists it as
having asked for the agent (``wake_digest``). Each used to decide for itself,
and an agent was woken with nothing to read, or read a turn nobody rang for,
wherever they disagreed. They all ask here now.

The rule (``contracts/asks.json`` holds its cases):

- Only chat asks: an ``exchange`` carrying a ``message`` or a ``reply`` with
  text. Presence, pings, notices and commits ask nobody.
- Nobody asks themselves.
- A mention asks (``mention``, or ``interrupt`` for ``@!``), by the hub's one
  mention rule (``persister.parse_mentions``: not silent, not in code, any
  letter case). Two exceptions: a mention of an engine summons it rather than
  asking it, and a text that summons a conductor asks nobody it names, since
  they are bound to its roles and the conductor asks each in its turn.
- A ``message`` asks its recipients (``turn``): how the aligner and the
  conductor put a question to one member.
- A ``reply`` asks only whoever it mentions. Its recipient is whoever the
  replier last heard from (``respond`` fills it in), not a choice to ask them.
"""

from __future__ import annotations

from typing import Any, Literal

from app.services.agent_registry import norm_handle
from app.services.persister import parse_interrupt_mentions, parse_mentions

Reason = Literal["mention", "turn", "interrupt"]

#: The payloads that can ask anything: chat.
CHAT_PAYLOADS = frozenset({"message", "reply"})


def _norm(handle: object) -> str:
    return norm_handle(handle) or ""


def _engine_kind(room: str | None, handle: str) -> str | None:
    if room is None:
        return None
    from app.services.aligner import _registered_engine_kind

    return _registered_engine_kind(room, handle)


def asks(content: dict[str, Any], handle: str, *, room: str | None = None) -> Reason | None:
    """Why the message ``content`` asks ``handle`` for something, or ``None``.

    ``content`` is a transcript record's content: its text under ``content``
    and its envelope under ``l9``. ``room`` is where to look up which handles
    are engines; without one, none are.
    """
    env = content.get("l9") or {}
    header = env.get("header") or {}
    if header.get("kind") != "exchange":
        return None
    payload = (env.get("payload") or {}).get("type")
    text = content.get("content")
    if payload not in CHAT_PAYLOADS or not isinstance(text, str) or not text.strip():
        return None
    me = _norm(handle)
    actors = [a for a in (header.get("participants") or {}).get("actors") or [] if a]
    ids = [_norm(a.get("id")) if isinstance(a, dict) else "" for a in actors]
    if not me or (ids and ids[0] == me):
        return None
    mentioned = [_norm(m) for m in parse_mentions(text)]
    why: Reason
    if me in mentioned:
        if _engine_kind(room, me) is not None:
            return None
        interrupting = {_norm(m) for m in parse_interrupt_mentions(text)}
        why = "interrupt" if me in interrupting else "mention"
    elif payload == "message" and me in ids[1:]:
        why = "turn"
    else:
        return None
    # Looked up last: it reads a manifest per handle mentioned.
    if any(_engine_kind(room, m) == "conductor" for m in mentioned):
        return None
    return why


def asked(content: dict[str, Any], room: str | None = None) -> dict[str, Reason]:
    """Everyone ``content`` asks, each with why: its recipients and whoever it
    mentions, each held to :func:`asks`. What the doorbell rings for."""
    header = (content.get("l9") or {}).get("header") or {}
    actors = (header.get("participants") or {}).get("actors") or []
    candidates = [a.get("id") for a in actors[1:] if isinstance(a, dict)]
    text = content.get("content")
    if isinstance(text, str):
        candidates += parse_mentions(text)
    found: dict[str, Reason] = {}
    for candidate in candidates:
        name = _norm(candidate)
        if name and name not in found and (why := asks(content, name, room=room)):
            found[name] = why
    return found
