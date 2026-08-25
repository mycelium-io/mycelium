# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Messages API — POST + list + event-status PATCH.

Backed by an in-memory store; publishes to the
in-process bus so the SSE stream sees writes live. The SLIM channel's durable
transcript is owned by the persister (``services/persister.py``); this
HTTP path stays the UI's post/list surface until SSE/``stream.py`` retires.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from app.bus import bus, room_channel
from app.schemas import (
    PROSE_MESSAGE_TYPES,
    STATEFUL_EVENT_KINDS,
    EventStatusUpdate,
    MessageAmend,
    MessageCreate,
    MessageListResponse,
    MessageRead,
    MessageType,
)
from app.services import actor, in_memory_store, l9, persister, principals, room_channels, tasks
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/messages", tags=["messages"])

# Shortest id prefix an amend may name its target by. Short enough for the id the
# CLI prints, long enough that a prefix match is a lookup rather than a guess.
_MIN_ID_PREFIX = 6


def _resolve_channel(name: str) -> tuple[str, in_memory_store.PresenceSession | None]:
    """Resolve a path name to its message channel key and optional session shim.

    Real room → (room_name, None). A ``{parent}:session:{short}`` display name →
    (display_name, shim). 404 if neither resolves.
    """
    if ":session:" in name:
        parent, _, _short = name.partition(":session:")
        coord = in_memory_store.get_session(parent)
        if coord is not None and coord.display_name == name:
            return name, coord
    if room_exists(name):
        return name, None
    raise HTTPException(status_code=404, detail="Room or session not found")


def _room_episode(
    room: str, coord: in_memory_store.PresenceSession | None, episode: str | None
) -> str | None:
    """The episode a stored row carries: the named thread, or the room's own.

    A coordination session is not a room and has no channel, so it stays
    episode-less; everywhere else "no thread" is the ``live`` URN spelled out.
    """
    if coord is not None:
        return episode
    return episode or l9.live_episode_urn(room)


@router.post("", response_model=MessageRead, status_code=201)
async def send_message(room_name: str, payload: MessageCreate, request: Request):
    """Send a message to a room; publish it to the room's live stream."""
    channel, coord = _resolve_channel(room_name)

    # Token-verified sender; fall back to payload handle if unauthenticated.
    # Delegation-aware, like /reply: a principal may announce as a handle that
    # granted it access via owner/allow_from, which is how one shared workload
    # credential posts under a distinct per-agent handle. The grant is explicit on
    # the target manifest, so this is authorized delegation, not impersonation.
    base_room = channel.split(":session:", 1)[0]
    sender_handle = actor.bind_delegated_actor(
        request, base_room, payload.sender_handle, field="sender_handle"
    )

    # Prevent impersonation: only engines post as engine handles.
    reason = principals.post_rejection_reason(base_room, sender_handle, allow_unregistered=True)
    if reason:
        raise HTTPException(status_code=403, detail=reason)

    # A thread write has to name a thread the room has, and stay out of a
    # negotiation it is not part of. Refused before anything is stored, so a
    # rejected write leaves nothing behind.
    if payload.episode and not l9.is_live_episode(base_room, payload.episode):
        if coord is not None:
            raise HTTPException(
                status_code=409,
                detail="A coordination session has no threads to post into",
            )
        refusal = tasks.thread_write_refusal(base_room, sender_handle, payload.episode)
        if refusal is not None:
            raise HTTPException(status_code=refusal.status, detail=refusal.detail)

    msg = in_memory_store.StoredMessage(
        room_name=None if coord else channel,
        coordination_session_id=coord.id if coord else None,
        sender_handle=sender_handle,
        recipient_handle=payload.recipient_handle,
        message_type=payload.message_type,
        content=payload.content,
        # Always the URN, never a bare ``None`` for "the room": the transcript
        # projection stamps ``live`` on the same message, and a row that agrees
        # with its own transcript copy is what makes ``?episode=<live>`` mean
        # "the room without its threads" — the read a legible main channel needs.
        episode=_room_episode(base_room, coord, payload.episode),
    )
    if payload.metadata is not None:
        meta = payload.metadata.model_dump(exclude_none=True)
        msg.event_metadata = meta
        msg.event_kind = payload.metadata.kind
        msg.event_status = payload.metadata.status
        if payload.metadata.ttl_seconds:
            msg.event_expires_at = datetime.now(UTC) + timedelta(
                seconds=payload.metadata.ttl_seconds
            )

    notify_payload: dict = {
        "id": str(msg.id),
        "sender_handle": msg.sender_handle,
        "recipient_handle": msg.recipient_handle,
        "message_type": msg.message_type,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
    }
    if msg.event_metadata is not None:
        notify_payload["metadata"] = msg.event_metadata
    if coord is not None:
        notify_payload["coordination_session_id"] = str(coord.id)
    notify_payload["room_name"] = channel
    if msg.episode:
        notify_payload["episode"] = msg.episode

    # Human-in-the-room: backend publishes onto the channel as proxy for live SLIM
    # rooms, parsing ``@`` recipients and raising consent for absent mentions. The
    # persister records to the durable transcript (source of truth), so don't also
    # write in_memory_store/bus here (would duplicate). Non-SLIM paths use direct write.
    published = False
    if (
        coord is None
        and msg.message_type == MessageType.BROADCAST
        and room_channels.manager.is_live(channel)
    ):
        result = await room_channels.manager.publish_human(
            channel, sender=msg.sender_handle, text=msg.content, episode=payload.episode
        )
        published = result is not None
        if result is not None:
            # Correlation key: the same envelope the persister records to the
            # transcript, so a cold read dedups this row against its transcript copy.
            msg.message_id = result.message_id
    # The human's message always lands in ``in_memory_store`` — its id backs PATCH /
    # event semantics and it's the live view. The persister records the same
    # message to the durable transcript (the read path's source of truth); the two
    # dedup by ``message_id`` on read. When published, the persister owns the bus
    # push, so only the un-published path publishes here.
    in_memory_store.add_message(channel, msg)
    if not published:
        bus.publish(room_channel(channel), notify_payload)

    # Exactly one ping per threaded write, whatever the message type and whether
    # or not the channel is up. Raised here rather than inside ``publish_human``
    # because that only sees broadcasts over a live channel: an ``event`` into a
    # thread, or any write while the channel is down, would move a task in
    # silence, and the ping is the only thing that surfaces a thread into the room.
    await room_channels.manager.raise_ping(
        base_room, episode=msg.episode, sender=msg.sender_handle, message_id=msg.message_id
    )
    return MessageRead.model_validate(msg)


def _read_messages(
    channel: str, coord: in_memory_store.PresenceSession | None
) -> list[in_memory_store.StoredMessage]:
    """The room view: durable conversational history + in-memory event-ledger rows.

    A coordination session has no transcript, so it is the in-memory rows alone;
    a real room is the merged view ``persister.room_conversation`` builds.
    """
    if coord is not None:
        return in_memory_store.list_messages(channel)
    return persister.room_conversation(channel)


@router.get("", response_model=MessageListResponse)
async def list_messages(
    room_name: str,
    limit: int = Query(50, le=500),
    offset: int = 0,
    sender: str | None = None,
    message_type: str | None = None,
    kind: str | None = Query(None, description="Filter events by metadata.kind"),
    status: str | None = Query(None, description="Filter events by ledger status"),
    since: datetime | None = Query(None, description="Only messages created at/after this time"),
    episode: str | None = Query(
        None, description="Only messages belonging to this L9 episode URN (one negotiation/session)"
    ),
):
    """List messages in a room (or coordination session), newest first."""
    channel, coord = _resolve_channel(room_name)
    now = datetime.now(UTC)

    messages = _read_messages(channel, coord)
    filtered = []
    for m in messages:
        if m.event_expires_at is not None and m.event_expires_at <= now:
            continue
        if sender and m.sender_handle != sender:
            continue
        if message_type and m.message_type != message_type:
            continue
        if kind and m.event_kind != kind:
            continue
        if status and m.event_status != status:
            continue
        if since and m.created_at < since:
            continue
        if episode and m.episode != episode:
            continue
        filtered.append(m)

    filtered.sort(key=lambda m: m.created_at, reverse=True)
    total = len(filtered)
    page = filtered[offset : offset + limit]

    return MessageListResponse(
        messages=[MessageRead.model_validate(m) for m in page],
        total=total,
    )


@router.get("/l9")
async def list_l9_wire(room_name: str, limit: int = Query(200, le=1000)) -> list[dict]:
    """The room's L9 wire feed, replayed from the transcript (oldest first).

    Backfills the live L9 inspector: the SSE bus carries no history, so a freshly
    opened tab would otherwise start empty. Frames are the exact shape the bus
    pushes, so the client projects backfill and live frames identically.
    """
    channel, coord = _resolve_channel(room_name)
    if coord is not None:
        return []  # a coordination session has no durable transcript
    return persister.l9_wire_history(channel, limit=limit)


def _find_amend_target(
    messages: list[in_memory_store.StoredMessage], message_id: str
) -> in_memory_store.StoredMessage | None:
    """Resolve ``message_id`` to a message in this room's view.

    A message carries two ids — the row id every client already holds and the
    envelope id it rode the channel under — so either identifies it, as does an
    unambiguous prefix of one (what a reader has in front of them is the short
    form the CLI prints).
    """
    for m in messages:
        if str(m.id) == message_id or m.message_id == message_id:
            return m
    if len(message_id) < _MIN_ID_PREFIX:
        return None
    matched = [
        m
        for m in messages
        if str(m.id).startswith(message_id) or (m.message_id or "").startswith(message_id)
    ]
    return matched[0] if len(matched) == 1 else None


@router.post("/{message_id}/amend", response_model=MessageRead, status_code=201)
async def amend_message(
    room_name: str,
    message_id: str,
    payload: MessageAmend,
    request: Request,
):
    """Revise an earlier message by posting an amendment of it.

    Additive, never destructive: the amendment is its own ``exchange:amend``
    message, parented on the one it revises, and the transcript keeps every
    version. The read path (``persister.collapse_amendments``) folds the chain,
    so the room sees one message carrying the newest text, marked edited.

    Only the original sender may amend — an amendment from anyone else would put
    words in someone's mouth under their name.
    """
    channel, coord = _resolve_channel(room_name)
    base_room = channel.split(":session:", 1)[0]
    sender_handle = actor.bind_delegated_actor(
        request, base_room, payload.sender_handle, field="sender_handle"
    )

    messages = _read_messages(channel, coord)
    target = _find_amend_target(messages, message_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Message not found in this room")
    if target.sender_handle != sender_handle:
        raise HTTPException(
            status_code=403,
            detail=f"Only @{target.sender_handle} can amend their own message",
        )
    if target.message_type not in PROSE_MESSAGE_TYPES:
        raise HTTPException(
            status_code=409,
            detail=f"Message type {target.message_type!r} is not chat — nothing to amend",
        )

    # An amendment lands in the thread of the message it revises — never in the
    # room. Publishing it to ``live`` would echo a thread's prose onto the main
    # channel, which is the one thing a thread exists to prevent, and the
    # ``?episode=`` read of that thread would not show the revision it folded in.
    # It is a write into that thread, so it passes the same guard as any other:
    # a roster that froze after the original message must still hold.
    refusal = tasks.thread_write_refusal(base_room, sender_handle, target.episode)
    if refusal is not None:
        raise HTTPException(status_code=refusal.status, detail=refusal.detail)

    # The envelope id when the target rode the channel; its row id otherwise (a
    # message posted while the channel was down never got one). Either way the
    # amendment names something the read path can resolve.
    amends = target.message_id or str(target.id)

    msg = in_memory_store.StoredMessage(
        room_name=None if coord else channel,
        coordination_session_id=coord.id if coord else None,
        sender_handle=sender_handle,
        recipient_handle=target.recipient_handle,
        message_type=target.message_type,
        content=payload.content,
        amends=amends,
        episode=_room_episode(base_room, coord, target.episode),
    )

    published = False
    if coord is None and room_channels.manager.is_live(channel):
        result = await room_channels.manager.publish_human(
            channel,
            sender=sender_handle,
            text=payload.content,
            subkind=l9.AMEND_SUBKIND,
            parents=[amends],
            episode=target.episode,
        )
        published = result is not None
        if result is not None:
            msg.message_id = result.message_id

    in_memory_store.add_message(channel, msg)
    if not published:
        bus.publish(
            room_channel(channel),
            {
                "id": str(msg.id),
                "sender_handle": msg.sender_handle,
                "recipient_handle": msg.recipient_handle,
                "message_type": msg.message_type,
                "content": msg.content,
                "amends": amends,
                "created_at": msg.created_at.isoformat(),
                "room_name": channel,
                "episode": msg.episode,
            },
        )

    # Exactly one ping per threaded write, whatever the message type and whether
    # or not the channel is up. Raised here rather than inside ``publish_human``
    # because that only sees broadcasts over a live channel: an ``event`` into a
    # thread, or any write while the channel is down, would move a task in
    # silence, and the ping is the only thing that surfaces a thread into the room.
    await room_channels.manager.raise_ping(
        base_room, episode=msg.episode, sender=sender_handle, message_id=msg.message_id
    )

    # Answer with the folded message — the row the room now reads — rather than
    # the amendment, so a client refreshes to exactly what it was handed.
    revised = _find_amend_target(_read_messages(channel, coord), str(target.id))
    return MessageRead.model_validate(revised or msg)


@router.patch("/{message_id}", response_model=MessageRead)
async def update_event_status(
    room_name: str,
    message_id: UUID,
    payload: EventStatusUpdate,
):
    """Transition a stateful event's status (open -> in_progress -> resolved)."""
    channel, coord = _resolve_channel(room_name)

    msg = in_memory_store.find_message(message_id)
    in_target = msg is not None and (
        (coord is None and msg.room_name == channel)
        or (coord is not None and msg.coordination_session_id == coord.id)
    )
    if msg is None or not in_target:
        raise HTTPException(status_code=404, detail="Message not found in this room")
    if msg.message_type != MessageType.EVENT or not msg.event_kind:
        raise HTTPException(status_code=409, detail="Not an event message")
    if msg.event_kind not in STATEFUL_EVENT_KINDS and msg.event_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Event kind {msg.event_kind!r} is stateless — no status to transition",
        )

    msg.event_status = payload.status
    meta = dict(msg.event_metadata or {})
    meta["status"] = payload.status
    meta["status_updated_at"] = datetime.now(UTC).isoformat()
    msg.event_metadata = meta

    notify_payload = {
        "id": str(msg.id),
        "sender_handle": msg.sender_handle,
        "recipient_handle": msg.recipient_handle,
        "message_type": msg.message_type,
        "content": msg.content,
        "metadata": msg.event_metadata,
        "created_at": msg.created_at.isoformat(),
        "status_transition": payload.status,
        "room_name": channel,
    }
    bus.publish(room_channel(channel), notify_payload)

    return MessageRead.model_validate(msg)
