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

Both take an optional **thread** — the episode URN of a task, or of a
negotiation inside one. A thread is a tag over the room's own channel, so this is
one field on each call rather than a second transport: ``await?episode=`` narrows
what wakes the handle (against that thread's own persisted cursor, so watching a
task consumes nothing from the room inbox behind it), and ``reply``'s ``episode``
names where the answer lands. Writing into a thread raises a **ping** in the room
— that a task moved, never what was said in it.

No client SLIM connection, no backgrounding, no compound shell — just two simple
commands, which is all a headless/allowlisted agent can safely issue.
"""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services import actor, l9, principals, room_channels, tasks
from app.services.filesystem import room_exists
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content, serialize_envelope
from app.services.persister import record_episode

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
# Payloads that are never an addressed turn however they are actor-labelled:
# presence/keepalive are liveness, a ``ping`` is the signal that a *thread* moved,
# and a ``notice`` is the signal that the *board* moved (a task filed, claimed,
# resolved) — all nudges to look, not turns to take. Excluded structurally here so
# a resident loop consumes one silently rather than reasoning about it.
_UNADDRESSED_PAYLOADS = frozenset(
    {"presence", "keepalive", l9.PING_PAYLOAD_TYPE, l9.NOTICE_PAYLOAD_TYPE}
)

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
    if ((env.get("payload") or {}).get("type")) in _UNADDRESSED_PAYLOADS:
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


def _refuse_thread_write(refusal: tasks.ThreadRefusal | None) -> None:
    """Answer a refused thread write, or return and let the write proceed.

    A room write is unchanged; a *thread* write has to name a thread the room
    has and stay out of a negotiation it is not part of — the rule and its
    reasoning live in :func:`app.services.tasks.episode_write_rejection`. This is
    the seam that keeps a handle from side-channelling a position into someone
    else's negotiation by naming its URN.
    """
    if refusal is not None:
        raise HTTPException(status_code=refusal.status, detail=refusal.detail)


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
async def await_message(
    room_name: str,
    request: Request,
    handle: str,
    timeout: int = 0,
    # Annotated rather than a ``Query(...)`` default: the default is then a real
    # ``None``, so calling this as a plain function (as the unit tests do) scopes
    # to the room instead of to a truthy ``Query`` object.
    episode: Annotated[
        str | None,
        Query(
            description=(
                "Wake only on this thread (an episode URN). Omit to wake on anything "
                "addressed to the handle anywhere in the room."
            )
        ),
    ] = None,
):
    """Long-poll for the next message addressed to ``handle`` (server-held member).

    ``episode`` narrows the wake to one thread — a task being coordinated
    in, or a negotiation inside one. It narrows *only* the wake: the handle's
    presence lease stays room-scoped (a member of a thread is a member of the
    room), and so does its room-wide delivery position, so scoping to a task
    never eats mentions made to it elsewhere. The thread's own position is
    persisted the same way, so a restart mid-thread resumes rather than
    re-serving.
    """
    import time as _time

    from app.services import metrics as _metrics

    _t0 = _time.monotonic()
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
    #
    # A thread-scoped call reads and commits a *different* cursor over the same
    # transcript — the thread's — so watching one task consumes nothing from the
    # handle's room inbox, and vice versa.
    scoped = episode if episode and not l9.is_live_episode(room_name, episode) else None

    def _position() -> int:
        return (
            persister.episode_position(handle, scoped) if scoped else persister.log.position(handle)
        )

    def _commit(pos: int) -> None:
        if scoped:
            persister.advance_episode_cursor(handle, scoped, pos)
        else:
            persister.advance_cursor(handle, pos)

    loop = asyncio.get_event_loop()
    deadline = loop.time() + (timeout if timeout > 0 else _MAX_WAIT_S)
    while True:
        records = persister.log.records
        i = _position()
        while i < len(records):
            record = records[i]
            i += 1
            ep = record_episode(record)
            if scoped and ep != scoped:
                continue
            if not scoped and ep and not l9.is_live_episode(room_name, ep):
                # Already served to this handle via a --task-scoped read of this
                # same thread (that path never advances the room cursor, on
                # purpose — see test_watching_a_thread_leaves_the_room_inbox_alone).
                # No fork needed on *this* side: EpisodeCursors.position() already
                # defaults an un-forked thread's position to the room-wide one
                # (its own docstring — "the fork happens where it is standing"),
                # and _commit(i) below is about to move that room-wide position to
                # exactly here, so the next scoped reader's default lands right
                # past this record with no extra write.
                if persister.episode_position(handle, ep) >= i:
                    continue
            if _addressed_to(record.content, handle):
                _commit(i)
                _last_tick[key] = record.content
                room_channels.manager.refresh_lease(room_name, handle)
                _metrics.record_await_poll(
                    room=room_name,
                    handle=handle,
                    duration_ms=(_time.monotonic() - _t0) * 1000.0,
                    delivered=True,
                )
                return _describe(room_name, handle, record)
        # Nothing addressed in the scanned range: consume it (advance past the
        # observer/broadcast turns this handle doesn't await) and keep polling.
        _commit(len(records))
        if loop.time() >= deadline:
            _metrics.record_await_poll(
                room=room_name,
                handle=handle,
                duration_ms=(_time.monotonic() - _t0) * 1000.0,
                delivered=False,
            )
            return {"room": room_name, "handle": handle, "message": None}
        room_channels.manager.refresh_lease(room_name, handle)
        await asyncio.sleep(_POLL_INTERVAL_S)


class ReplyBody(BaseModel):
    handle: str = Field(..., description="The handle publishing the reply")
    text: str = Field(..., description="The reply / position prose (may carry a position marker)")
    episode: str | None = Field(
        None,
        description=(
            "Thread to reply into (an episode URN). Overrides the episode inherited "
            "from the tick that woke the handle; omit to answer where you were asked."
        ),
    )


@router.post("/reply")
async def post_reply(room_name: str, body: ReplyBody, request: Request):
    """Publish ``handle``'s reply as an L9 agent exchange the aligner scores."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    # A verified token names the replier; unauthenticated, the body's handle does.
    # Either way it is resolved here, so the transcript sender and the L9 actor
    # below are the same handle the room-membership guard passed. Delegation-aware
    # (owner/allow_from), matching await_message's authorize_handle just below —
    # an agent's owner can reply on its behalf, not just watch for its turns.
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
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
    # Where the tick was asked, and where this reply lands. Read once: two
    # accessors of the same field drift, and the answer decides both the target
    # and whether the causal edge below survives.
    tick_episode = woke_msg.get("episode") or l9.live_episode_urn(room_name)
    # An explicit target wins over the inherited one: a reply answers where it was
    # asked by default, which is what keeps a resident loop threaded without the
    # agent tracking URNs — but a caller that names a thread means that thread.
    episode = body.episode or tick_episode
    _refuse_thread_write(tasks.thread_write_refusal(room_name, handle, episode))
    topic = ((woke_header.get("context") or {}).get("topic")) or l9.topic_urn(room_name)
    # Parent onto the tick only when the reply lands where the tick did. A reply
    # redirected into another thread is not an answer to that tick, and a causal
    # edge reaching across threads would put one thread's message in another's
    # chain — read back as a conversation that never happened.
    answers_the_tick = tick_episode == episode
    parents = [woke_msg["id"]] if answers_the_tick and woke_msg.get("id") else []
    recipients = [tick_sender] if answers_the_tick and tick_sender else [l9.SYSTEM_ACTOR_ID]

    envelope = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=handle,
        sender_role="agent",
        recipients=recipients,
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
    # Under an identity tier (#666), send through the actor's **custodial session**
    # so the wire sender is @handle's own MLS identity — cryptographic, not
    # backend-stamped. The moderator receives that real MLS message and dedups it
    # against the ``ingest_local`` above by message id, so the transcript stays
    # single-copy. A session that can't be stood up falls back to a moderator
    # broadcast (attribution degrades to app-level for that one message; liveness is
    # preserved). Under the PSK default ``send_as_custodian`` is a no-op and this is
    # the prior moderator send.
    wire = serialize_envelope(envelope, extra={"content": clean})
    sent_as_actor = await room_channels.manager.send_as_custodian(room_name, handle, wire)
    if not sent_as_actor:
        try:
            await managed.channel.send(envelope, extra={"content": clean})
        except Exception:
            pass
    await room_channels.manager.raise_ping(
        room_name,
        episode=episode,
        sender=handle,
        message_id=envelope.header.message.id if envelope.header.message else None,
    )
    # herdr wake-on-mention, agent→agent leg: a reply that tags another handle
    # should wake it the same as a human's tag does. Shares the one hook the
    # human POST /messages path uses; ``exclude`` skips a self-mention so a reply
    # naming its own handle doesn't enqueue a self-wake.
    room_channels.manager.enqueue_herdr_wakes_for_mentions(room_name, clean, exclude=handle)
    return {
        "room": room_name,
        "handle": handle,
        "message_id": envelope.header.message.id if envelope.header.message else None,
    }
