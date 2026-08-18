# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Server-held participation — ``await`` (long-poll) + ``reply`` over HTTP.

A turn-based agent (a Claude Code session, a subagent) can't hold a live SLIM
socket *between* its reasoning turns — the same limitation the daemon was built to
paper over. So membership is **server-held**: the backend keeps the agent present
in the room (a lease, refreshed on every call) and the durable transcript is the
delivery queue. The agent participates with two plain, stateless HTTP calls:

* ``GET  /rooms/{room}/await``  — long-poll: block until the next message addressed
  to the handle (a mediator tick or an ``@``-mention) appears past a **persistent
  per-handle cursor**, then return it. Because the cursor rides the durable
  transcript, a tick is *never missed* in the gap between one await and the next —
  which is exactly what the client-held one-shot ``await`` could not guarantee.
* ``POST /rooms/{room}/reply`` — publish the agent's reply as an L9 ``exchange``
  (role ``agent``) recorded into the transcript, which the aligner's poll scores
  as a position.

No client SLIM connection, no backgrounding, no compound shell — just two simple
commands, which is all a headless/allowlisted agent can safely issue.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import actor, l9, principals, room_channels
from app.services.filesystem import room_exists
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content, serialize_envelope

router = APIRouter(prefix="/rooms/{room_name}", tags=["participate"])


# The delivery cursor itself lives on the durable inbox (``persister.log``), so it
# survives a restart and starts a brand-new handle at its ``agent create`` /
# first-mention anchor rather than "now". Only the last served tick is kept
# process-local here: it's a best-effort convenience so a following ``reply``
# parents onto the tick that woke the caller, and losing it on restart just drops
# that one parent edge — never a message.
_last_tick: dict[tuple[str, str], dict[str, Any]] = {}

_POLL_INTERVAL_S = 0.4
_MAX_WAIT_S = 3600.0

# An agent may end a reply with a position marker like
# ``[[mycelium: confidence=0.85 stance=accept]]``; those fields are lifted onto the
# L9 payload so the aligner can score convergence, and stripped from the prose.
_MARKER_RE = re.compile(r"\[\[\s*mycelium\s*:(.*?)\]\]", re.IGNORECASE | re.DOTALL)
_STANCE_TO_ACTION = {
    "accept": "accept",
    "agree": "accept",
    "yes": "accept",
    "reject": "reject",
    "block": "reject",
    "no": "reject",
}


def _norm(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def _parse_marker(text: str) -> tuple[dict[str, Any], str]:
    """Lift ``confidence``/``stance`` out of any ``[[mycelium: …]]`` marker; strip it."""
    payload: dict[str, Any] = {}
    for match in _MARKER_RE.finditer(text):
        for key, raw in re.findall(r"(\w+)\s*=\s*(\S+)", match.group(1)):
            k = key.lower()
            if k == "confidence":
                try:
                    val = float(raw)
                except ValueError:
                    continue
                if 0.0 <= val <= 1.0:
                    payload["confidence"] = val
            elif k in ("stance", "action"):
                action = _STANCE_TO_ACTION.get(raw.lower())
                if action:
                    payload["action"] = action
    clean = _MARKER_RE.sub("", text).strip() or text.strip()
    return payload, clean


def _addressed_to(content: dict[str, Any], handle: str) -> bool:
    """True when a transcript record is an exchange addressed to ``handle``.

    Addressed = the handle is an L9 recipient, or ``@handle`` appears in the human
    text — and the sender is not the handle itself (loop guard). Presence/keepalive
    are never addressed turns.
    """
    env = content.get("l9") or {}
    header = env.get("header") or {}
    if header.get("kind") != "exchange":
        return False
    if ((env.get("payload") or {}).get("type")) in ("presence", "keepalive"):
        return False
    actors = (header.get("participants") or {}).get("actors") or []
    sender = actors[0].get("id") if actors and isinstance(actors[0], dict) else None
    if sender and _norm(sender) == _norm(handle):
        return False
    recipients = [a.get("id") for a in actors[1:] if isinstance(a, dict)]
    if any(_norm(r) == _norm(handle) for r in recipients if r):
        return True
    text = (content.get("content") or "").lower()
    needle = f"@{handle.lower()}"
    idx = text.find(needle)
    if idx == -1:
        return False
    nxt = text[idx + len(needle)] if idx + len(needle) < len(text) else ""
    return not (nxt.isalnum() or nxt in "_-")


def _describe(room: str, handle: str, record: Any) -> dict[str, Any]:
    content = record.content
    header = (content.get("l9") or {}).get("header") or {}
    message = header.get("message") or {}
    context = header.get("context") or {}
    return {
        "room": room,
        "handle": handle,
        "prompt": content.get("content") or "",
        "sender": record.sender,
        "episode": message.get("episode"),
        "topic": context.get("topic"),
        "message_id": record.message_id,
    }


@router.get("/await")
async def await_message(room_name: str, request: Request, handle: str, timeout: int = 0):
    """Long-poll for the next message addressed to ``handle`` (server-held member)."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    # Draining a queue consumes it: the cursor advances, so a served turn is not
    # served again. A verified token may therefore only drain its own handle or one
    # that granted it — otherwise @bob's token could intercept @alice's coordination.
    actor.authorize_handle(request, room_name, handle)
    managed = await room_channels.manager.provision(room_name)
    room_channels.manager.refresh_lease(room_name, handle)
    if managed is None or managed.persister is None:
        return {"room": room_name, "handle": handle, "message": None}
    persister = managed.persister
    key = (room_name, handle)
    # The cursor rides the durable inbox: its first read is the handle's persisted
    # delivery position — anchored at the mention that summoned it (``record()``
    # holds an @-addressed turn for an untracked recipient) and preserved across a
    # backend restart. So a message sitting in the transcript before this handle's
    # first ``await`` is delivered, not skipped.
    loop = asyncio.get_event_loop()
    deadline = loop.time() + (timeout if timeout > 0 else _MAX_WAIT_S)
    while True:
        records = persister.log.records
        i = persister.log.position(handle)
        while i < len(records):
            record = records[i]
            i += 1
            if _addressed_to(record.content, handle):
                persister.advance_cursor(handle, i)
                _last_tick[key] = record.content
                room_channels.manager.refresh_lease(room_name, handle)
                return _describe(room_name, handle, record)
        # Nothing addressed in the scanned range: consume it (advance past the
        # observer/broadcast turns this handle doesn't await) and keep polling.
        persister.advance_cursor(handle, len(records))
        if loop.time() >= deadline:
            return {"room": room_name, "handle": handle, "message": None}
        room_channels.manager.refresh_lease(room_name, handle)
        await asyncio.sleep(_POLL_INTERVAL_S)


class ReplyBody(BaseModel):
    handle: str = Field(..., description="The handle publishing the reply")
    text: str = Field(..., description="The reply / position prose (may carry a position marker)")


@router.post("/reply")
async def post_reply(room_name: str, body: ReplyBody, request: Request):
    """Publish ``handle``'s reply as an L9 agent exchange the aligner scores."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    # A verified token names the replier; unauthenticated, the body's handle does.
    # Either way it is resolved here, so the transcript sender and the L9 actor
    # below are the same handle the room-membership guard passed.
    handle = actor.bind_actor(request, body.handle, field="handle")
    # The reply rides as sender_role="agent", so the handle must be a real
    # principal — a registered agent or a known user — and never an engine
    # (engines aren't impersonable). Guard before provisioning a channel.
    reason = principals.post_rejection_reason(room_name, handle, allow_unregistered=False)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    managed = await room_channels.manager.provision(room_name)
    room_channels.manager.refresh_lease(room_name, handle)
    if managed is None or managed.persister is None:
        raise HTTPException(status_code=503, detail="No live channel for room")

    payload_data, clean = _parse_marker(body.text)
    woke = _last_tick.get((room_name, handle)) or {}
    woke_header = (woke.get("l9") or {}).get("header") or {}
    woke_msg = woke_header.get("message") or {}
    woke_actors = (woke_header.get("participants") or {}).get("actors") or []
    tick_sender = (
        woke_actors[0].get("id") if woke_actors and isinstance(woke_actors[0], dict) else None
    )
    episode = woke_msg.get("episode") or l9.episode_urn(room_name, "live")
    topic = ((woke_header.get("context") or {}).get("topic")) or l9.topic_urn(room_name)
    parents = [woke_msg["id"]] if woke_msg.get("id") else []

    envelope = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=handle,
        sender_role="agent",
        recipients=[tick_sender] if tick_sender else [l9.SYSTEM_ACTOR_ID],
        topic=topic,
        payload_type="reply",
        payload_data=payload_data or {"action": "reply"},
        parents=parents,
    )
    content = serialize_content(envelope, extra={"content": clean})
    # Record into the transcript (the aligner polls it for positions). SLIM does
    # not echo a broadcast back to its own sender, so a local record is required —
    # then also broadcast so any client-connected members / the UI see it.
    # ``list_write=True`` so the reply is visible in the room view immediately, the
    # same store a ``room send`` broadcast lands in (no store divergence).
    managed.persister.ingest_local(envelope, content, list_write=True)
    # Under an identity tier (#666), send through the actor's **twin** so the wire
    # sender is @handle's own MLS identity — cryptographic, not backend-stamped.
    # The moderator receives that real MLS message and dedups it against the
    # ``ingest_local`` above by message id, so the transcript stays single-copy.
    # A twin that can't be stood up falls back to a moderator broadcast (attribution
    # degrades to app-level for that one message; liveness is preserved). Under the
    # PSK default ``send_as_twin`` is a no-op and this is the prior moderator send.
    wire = serialize_envelope(envelope, extra={"content": clean})
    sent_as_actor = await room_channels.manager.send_as_twin(room_name, handle, wire)
    if not sent_as_actor:
        try:
            await managed.channel.send(envelope, extra={"content": clean})
        except Exception:
            pass
    return {
        "room": room_name,
        "handle": handle,
        "message_id": envelope.header.message.id if envelope.header.message else None,
    }
