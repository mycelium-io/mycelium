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
    STATEFUL_EVENT_KINDS,
    EventStatusUpdate,
    MessageCreate,
    MessageListResponse,
    MessageRead,
    MessageType,
)
from app.services import actor, local_state, persister, principals, room_channels
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/messages", tags=["messages"])


def _resolve_channel(name: str) -> tuple[str, local_state.CoordSessionShim | None]:
    """Resolve a path name to its message channel key and optional session shim.

    Real room → (room_name, None). A ``{parent}:session:{short}`` display name →
    (display_name, shim). 404 if neither resolves.
    """
    if ":session:" in name:
        parent, _, _short = name.partition(":session:")
        coord = local_state.get_session(parent)
        if coord is not None and coord.display_name == name:
            return name, coord
    if room_exists(name):
        return name, None
    raise HTTPException(status_code=404, detail="Room or session not found")


@router.post("", response_model=MessageRead, status_code=201)
async def send_message(room_name: str, payload: MessageCreate, request: Request):
    """Send a message to a room; publish it to the room's live stream."""
    channel, coord = _resolve_channel(room_name)

    # Whoever a verified token says is calling is the sender; unauthenticated, the
    # body's handle stands as before.
    sender_handle = actor.bind_actor(request, payload.sender_handle, field="sender_handle")

    # A human posts under a self-asserted handle (may be unregistered), but no
    # one may pose as an engine — engines speak only through their own runtime.
    base_room = channel.split(":session:", 1)[0]
    reason = principals.post_rejection_reason(base_room, sender_handle, allow_unregistered=True)
    if reason:
        raise HTTPException(status_code=403, detail=reason)

    msg = local_state.StoredMessage(
        room_name=None if coord else channel,
        coordination_session_id=coord.id if coord else None,
        sender_handle=sender_handle,
        recipient_handle=payload.recipient_handle,
        message_type=payload.message_type,
        content=payload.content,
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

    # Human-in-the-room: for a real room with a live SLIM channel, the backend
    # publishes the human's message onto the channel as their proxy — ``@``-parsing
    # recipients so in-room agents wake, and raising consent for absent mentions.
    # The persister records it to the durable transcript (via ``ingest_local``),
    # which is the read path's source of truth, so we must NOT also write
    # ``local_state`` / ``bus.publish`` here (that would double it). The no-channel
    # path and event/non-broadcast messages have no persister, so they keep the
    # direct ``local_state`` write + legacy bus.
    published = False
    if (
        coord is None
        and msg.message_type == MessageType.BROADCAST
        and room_channels.manager.is_live(channel)
    ):
        result = await room_channels.manager.publish_human(
            channel, sender=msg.sender_handle, text=msg.content
        )
        published = result is not None
        if result is not None:
            # Correlation key: the same envelope the persister records to the
            # transcript, so a cold read dedups this row against its transcript copy.
            msg.message_id = result.message_id
    # The human's message always lands in ``local_state`` — its id backs PATCH /
    # event semantics and it's the live lens. The persister records the same
    # message to the durable transcript (the read path's source of truth); the two
    # dedup by ``message_id`` on read. When published, the persister owns the bus
    # push, so only the un-published path publishes here.
    local_state.add_message(channel, msg)
    if not published:
        bus.publish(room_channel(channel), notify_payload)

    return MessageRead.model_validate(msg)


def _read_messages(
    channel: str, coord: local_state.CoordSessionShim | None
) -> list[local_state.StoredMessage]:
    """The room view: durable conversational history + in-memory event-ledger rows.

    A coordination session has no transcript, so it is the in-memory rows alone;
    a real room is the merged view ``persister.room_conversation`` builds.
    """
    if coord is not None:
        return local_state.list_messages(channel)
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


@router.patch("/{message_id}", response_model=MessageRead)
async def update_event_status(
    room_name: str,
    message_id: UUID,
    payload: EventStatusUpdate,
):
    """Transition a stateful event's status (open -> in_progress -> resolved)."""
    channel, coord = _resolve_channel(room_name)

    msg = local_state.find_message(message_id)
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
