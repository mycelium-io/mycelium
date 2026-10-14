# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Whether a message asks a member for something, and why: the one rule.

Everything that reacts to being asked reads it here. The herdr doorbell queues
a wake (``persister`` → ``room_channels.ring_asked``), ``await`` hands the
message over as the agent's turn (``participate``), the wake digest lists it as
having asked for the agent (``wake_digest``), an engine is summoned, and a
persona or a worker answers. Each used to decide for itself, and an agent was
woken with nothing to read, or read a turn nobody rang for, wherever they
disagreed.

The rule is the same for every member and every sender, people, agents and
engines alike (``contracts/asks.json`` holds its cases):

- Only what says something asks: an ``exchange`` with text. The signals
  (presence, keepalive, a ping, a notice) and commits ask nobody. An aligner's
  turn rides as a ``tick``; it is said, so it asks like any message.
- Nobody asks themselves.
- A mention asks (``mention``, or ``interrupt`` for ``@!``), by the hub's one
  mention rule (``persister.parse_mentions``: not silent, not in code, any
  letter case).
- Anything but a ``reply`` asks its recipients (``turn``): how the aligner
  and the conductor put a question to one member.
- A ``reply`` asks only whoever it mentions. Its recipient is whoever the
  replier last heard from (``respond`` fills it in), not a choice to ask them.
"""

from __future__ import annotations

from typing import Any, Literal

from app.services import message_format
from app.services.agent_registry import norm_handle
from app.services.persister import parse_interrupt_mentions, parse_mentions

Reason = Literal["mention", "turn", "interrupt"]

#: What every member the hub plays is told about mentions, since what it
#: writes is posted as written and held to the same rule as anyone's. Agents
#: read the same thing in the CLI skill.
MENTION_ETIQUETTE = (
    "Writing @name asks that member to act, and wakes them. Write a bare @ only "
    "for whoever you are asking. To name someone without asking them, write "
    "@~name or just their name."
)

#: The payloads that say nothing: liveness, and the room's own signals that a
#: thread or the board moved. They never ask anyone.
SIGNAL_PAYLOADS = frozenset(
    {"presence", "keepalive", message_format.PING_PAYLOAD_TYPE, message_format.NOTICE_PAYLOAD_TYPE}
)


def _norm(handle: object) -> str:
    return norm_handle(handle) or ""


def asks(content: dict[str, Any], handle: str) -> Reason | None:
    """Why the message ``content`` asks ``handle`` for something, or ``None``.

    ``content`` is a transcript record's content: its text under ``content``
    and its envelope under ``l9``.
    """
    env = content.get("l9") or {}
    header = env.get("header") or {}
    if header.get("kind") != "exchange":
        return None
    payload = (env.get("payload") or {}).get("type")
    text = content.get("content")
    if payload in SIGNAL_PAYLOADS or not isinstance(text, str) or not text.strip():
        return None
    me = _norm(handle)
    actors = [a for a in (header.get("participants") or {}).get("actors") or [] if a]
    ids = [_norm(a.get("id")) if isinstance(a, dict) else "" for a in actors]
    if not me or (ids and ids[0] == me):
        return None
    if me in {_norm(m) for m in parse_mentions(text)}:
        interrupting = {_norm(m) for m in parse_interrupt_mentions(text)}
        return "interrupt" if me in interrupting else "mention"
    if payload != "reply" and me in ids[1:]:
        return "turn"
    return None


def asked(content: dict[str, Any]) -> dict[str, Reason]:
    """Everyone ``content`` asks, each with why, in the order they're named:
    whoever it mentions, then its recipients, each held to :func:`asks`."""
    header = (content.get("l9") or {}).get("header") or {}
    actors = (header.get("participants") or {}).get("actors") or []
    text = content.get("content")
    candidates = parse_mentions(text) if isinstance(text, str) else []
    candidates += [a.get("id") for a in actors[1:] if isinstance(a, dict)]
    found: dict[str, Reason] = {}
    for candidate in candidates:
        name = _norm(candidate)
        if name and name not in found and (why := asks(content, name)):
            found[name] = why
    return found
