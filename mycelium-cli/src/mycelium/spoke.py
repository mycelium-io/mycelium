# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The thin spoke — a room **member** that applies inbound ``knowledge`` locally.

A room's channel has exactly one moderator: the always-on backend that provisioned
it (``fastapi-backend/app/services/room_channels.py``). Standing up a second
backend against the same node and room does *not* share a group — each becomes its
own moderator with its own MLS session, so nothing crosses. Receiving another
machine's writes means joining as a **member**, which is what this module does.

The receive half of the memory-sync seam already existed on both sides and was
simply never connected across machines: the hub broadcasts a ``knowledge``
envelope on every ``memory set``, and :func:`mycelium.filesystem.apply_knowledge`
is the local applier (last-write-wins by version, idempotent re-delivery,
stale-base writes recorded as conflicts rather than clobbering). The spoke is the
process in between — it holds membership and feeds one to the other.

Deliberately *not* a persister. The backend's ``RoomPersister`` also owns the
transcript, delivery cursors, the SSE bus and episode hooks, all of which are
moderator-authoritative. A spoke is a passive consumer of one envelope kind, so it
borrows only the apply path; message-level dedup is unnecessary because the
version check already makes a replay a no-op.

Search stays hub-side: the CLI has no local embedding index, so memories that
arrive here are not searchable until a ``mycelium sync`` / ``mycelium memory
reindex`` against a backend.

Membership is gated by the room's shared-secret PSK (``mint_shared_secret``,
keyed on ``workspace/room``) — the same dev-tier D1 model every other member uses.
A spoke is exactly as authenticated as any connector, no more: per-agent identity
(JWT/SPIRE) remains a prerequisite for anything hosted or multi-user (issue #446).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mycelium.filesystem import apply_knowledge, get_room_dir
from mycelium.slim import l9
from mycelium.slim.client import SlimClient, SlimReceiveTimeout
from mycelium.slim.member import DEFAULT_JOIN_TIMEOUT_S, joined_member
from mycelium.slim.naming import DEFAULT_WORKSPACE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mycelium.filesystem import KnowledgeApplyResult

logger = logging.getLogger(__name__)

# How long a single receive waits before yielding control. A quiet room is the
# normal case, not an error: the timeout just paces the loop so a Ctrl-C is
# noticed promptly.
DEFAULT_RECEIVE_TIMEOUT_S = 30.0

# Mirrors the backend's ``l9.SYSTEM_ACTOR_ID`` — the actor recorded for a write
# that names none.
SYSTEM_ACTOR = "system"


@dataclass
class SpokeCounters:
    """What this spoke has done with the traffic it received.

    ``applied``/``conflicts`` mirror the backend persister's counters of the same
    name, so a spoke's health reads the same way as a hub's.
    """

    applied: int = 0
    conflicts: int = 0
    ignored: int = 0

    def record(self, result: KnowledgeApplyResult) -> None:
        if result.conflict:
            self.conflicts += 1
        elif result.applied:
            self.applied += 1
        else:
            self.ignored += 1


def knowledge_write_of(content: dict[str, Any]) -> dict[str, Any] | None:
    """The memory write a decoded message carries, or ``None`` if it carries none.

    ``None`` covers both "not a ``knowledge`` message" and "malformed payload" —
    neither is an error for a spoke, which sees a room's whole traffic and applies
    only the memory-sync slice of it. Subkind-agnostic on purpose: a
    ``distillation`` (compiled plan) and an ``extraction`` (raw ``memory set``)
    apply identically.
    """
    if l9.kind_of(content) != l9.KNOWLEDGE_KIND:
        return None
    data = l9.payload_data_of(content)
    key = data.get("key")
    body = data.get("content")
    if not isinstance(key, str) or not key or not isinstance(body, str):
        return None
    try:
        version = int(data.get("version", 1))
    except (TypeError, ValueError):
        version = 1
    actor = str(data.get("updated_by") or data.get("created_by") or SYSTEM_ACTOR)
    return {
        "key": key,
        "content": body,
        "version": version,
        "created_by": str(data.get("created_by") or actor),
        "updated_by": actor,
    }


def apply_message(room_dir: Path, payload: bytes) -> KnowledgeApplyResult | None:
    """Decode one inbound frame and apply the memory write it carries.

    Returns ``None`` when the frame is unparseable or carries no memory write.
    """
    content = l9.parse(payload)
    if content is None:
        return None
    write = knowledge_write_of(content)
    if write is None:
        return None
    return apply_knowledge(room_dir, **write)


async def receive_and_apply(
    session: Any,
    room_dir: Path,
    *,
    counters: SpokeCounters,
    on_apply: Callable[[KnowledgeApplyResult], None] | None = None,
    receive_timeout_s: float = DEFAULT_RECEIVE_TIMEOUT_S,
    max_messages: int | None = None,
) -> SpokeCounters:
    """Receive on ``session`` forever, applying every ``knowledge`` write locally.

    Runs until cancelled. ``max_messages`` bounds the loop for tests. A receive
    timeout is a quiet room, not a failure; a malformed frame is skipped rather
    than dropping membership, since one bad publisher must not take the spoke off
    the channel.
    """
    seen = 0
    while max_messages is None or seen < max_messages:
        try:
            message = await SlimClient.receive_message(session, timeout_s=receive_timeout_s)
        except SlimReceiveTimeout:
            continue
        seen += 1
        try:
            result = apply_message(room_dir, message.payload)
        except Exception:
            logger.exception("failed to apply an inbound message")
            continue
        if result is None:
            continue
        counters.record(result)
        if on_apply is not None:
            on_apply(result)
    return counters


async def run_spoke(
    *,
    api_url: str,
    node_endpoint: str,
    room: str,
    handle: str,
    workspace: str = DEFAULT_WORKSPACE,
    counters: SpokeCounters | None = None,
    on_joined: Callable[[], None] | None = None,
    on_apply: Callable[[KnowledgeApplyResult], None] | None = None,
    join_timeout_s: float = DEFAULT_JOIN_TIMEOUT_S,
    receive_timeout_s: float = DEFAULT_RECEIVE_TIMEOUT_S,
    max_messages: int | None = None,
) -> SpokeCounters:
    """Join ``room`` as a member and apply its ``knowledge`` traffic to this store.

    Writes land in this machine's own ``~/.mycelium/rooms/{room}/``, which is what
    makes the hub's ``memory set`` show up here.
    """
    tally = counters if counters is not None else SpokeCounters()
    async with joined_member(
        api_url=api_url,
        node_endpoint=node_endpoint,
        room=room,
        handle=handle,
        workspace=workspace,
        join_timeout_s=join_timeout_s,
    ) as session:
        if on_joined is not None:
            on_joined()
        await receive_and_apply(
            session,
            get_room_dir(room),
            counters=tally,
            on_apply=on_apply,
            receive_timeout_s=receive_timeout_s,
            max_messages=max_messages,
        )
    return tally
