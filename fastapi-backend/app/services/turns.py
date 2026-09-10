# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""One addressed turn over a room's channel: ask one handle, wait for its answer.

The primitive the aligner brokers a negotiation with, lifted out so anything
that puts a question to one member and needs that member's reply — a mediator
round, a step of a protocol, a review gate — asks it the same way.

Two properties are the whole contract. **One wake:** the prompt names exactly
one L9 recipient, and every ``@`` in the prose is neutralized, so the room reads
who was asked while only that handle's ``await`` returns. **Silence yields
nothing:** the wait is bounded, an empty string comes back on timeout, and the
caller decides what silence means (the mediator reads it as a reject and never
invents a position for a handle that did not speak).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

from app.services import l9
from app.services.agent_registry import norm_handle
from app.services.l9_models import Kind

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.services.l9_models import L9
    from app.services.persister import TranscriptRecord

logger = logging.getLogger(__name__)

#: The ``@`` sigil in front of a handle. The prompt a turn carries names the
#: other members in its prose (a broker's summary, a step's context); left as
#: is, every one of them would wake on the mention-in-text match. Stripping the
#: sigil keeps the names readable and the wake single.
MENTION_SIGIL = re.compile(r"@(?=\w)")


def neutralize_mentions(text: str) -> str:
    """``text`` with every ``@handle`` reduced to ``handle``."""
    return MENTION_SIGIL.sub("", text)


async def addressed_turn(
    managed: Any,
    persister: Any,
    *,
    sender: str,
    handle: str,
    episode: str,
    topic: str,
    prompt: str,
    is_reply: Callable[[TranscriptRecord], bool],
    timeout_s: float,
    poll_interval_s: float,
    payload_type: str = "tick",
    payload_data: dict[str, Any] | None = None,
    on_tick: Callable[[L9], None] | None = None,
    on_reply: Callable[[TranscriptRecord], None] | None = None,
) -> str:
    """Post ``prompt`` to ``handle`` alone, wait for its reply, return the prose.

    The prompt is recorded into the transcript like any message, so the room can
    follow along; the reply is the first record past it from ``handle`` that
    ``is_reply`` accepts. ``""`` when the send fails or ``timeout_s`` passes
    with no such record. ``on_tick`` sees the envelope once it is posted and
    ``on_reply`` the record that answered it, for a caller keeping its own
    episode record.
    """
    before = len(persister.log.records)
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        recipients=[handle],
        topic=topic,
        payload_type=payload_type,
        payload_data=payload_data,
    )
    try:
        await managed.post(env, neutralize_mentions(prompt), raise_on_send_failure=True)
    except Exception:
        logger.warning("failed to put a turn to @%s in %s", handle, episode)
        return ""
    if on_tick is not None:
        on_tick(env)

    pending = norm_handle(handle) or ""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        for record in persister.log.records[before:]:
            if (norm_handle(record.sender) or "") == pending and is_reply(record):
                if on_reply is not None:
                    on_reply(record)
                return record.content.get("content") or ""
        if loop.time() >= deadline:
            return ""
        await asyncio.sleep(poll_interval_s)
