# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""One addressed turn over a room's channel: ask one handle, wait for its answer.

The primitive the conductor puts each step's question with, kept apart so
anything that puts a question to one member and needs that member's reply — a
step of a flow, a review gate — asks it the same way.

Two properties are the whole contract. **One recipient:** the prompt names
exactly one message recipient, which asks that member (``asks.py``); the prose
is posted as written, so a mention in it asks whoever it names, the same as
anyone's, and a caller writes a bare ``@`` only for who it is asking. **Silence yields
nothing:** the wait is bounded, an empty string comes back on timeout, and the
caller decides what silence means (the conductor reads it as a ``silent``
stance and never invents a position for a handle that did not speak).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

from app.services import message_format
from app.services.agent_registry import norm_handle
from app.services.message_models import Kind

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.services.message_models import MyceliumMessage
    from app.services.persister import TranscriptRecord

logger = logging.getLogger(__name__)

#: The ``@`` sigil in front of a handle, with an interrupting ``@!``'s ``!``.
#: For reading a mention out of text the hub was handed (a summon's directive,
#: a summary it stores), never for changing what a member says.
MENTION_SIGIL = re.compile(r"@!?(?=\w)")


def neutralize_mentions(text: str) -> str:
    """``text`` with every ``@handle`` and ``@!handle`` reduced to ``handle``."""
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
    on_tick: Callable[[MyceliumMessage], None] | None = None,
    on_reply: Callable[[TranscriptRecord], None] | None = None,
    mention: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    """Post ``prompt`` to ``handle`` alone, wait for its reply, return the prose.

    The prompt is recorded into the transcript like any message, so the room can
    follow along; the reply is the first record past it from ``handle`` that
    ``is_reply`` accepts. ``""`` when the send fails, ``timeout_s`` passes
    with no such record, or ``cancelled`` says to give up. ``on_tick`` sees the
    envelope once it is posted and ``on_reply`` the record that answered it,
    for a caller keeping its own episode record.

    ``mention`` puts a real ``@handle`` at the front, so the member is asked
    by the mention as well as by being the recipient.
    """
    before = len(persister.log.records)
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        recipients=[handle],
        topic=topic,
        payload_type=payload_type,
        payload_data=payload_data,
    )
    text = prompt
    if mention:
        bare = norm_handle(handle) or handle
        if not text.startswith(f"@{bare}"):
            text = f"@{text}" if text.startswith(bare) else f"@{bare} {text}"
    try:
        await managed.post(env, text, raise_on_send_failure=True)
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
        if loop.time() >= deadline or (cancelled is not None and cancelled()):
            return ""
        await asyncio.sleep(poll_interval_s)
