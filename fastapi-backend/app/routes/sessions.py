# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Sessions API — tracks agent presence in rooms.

Presence is handled by SLIM: joining a room invites the agent into the
room's SLIM group channel (backend = moderator), and — when a channel is live —
membership on that channel is authoritative for who is present. ``local_state``
remains the metadata store (intent, context files) that SLIM membership doesn't
carry; it is also the sole fallback when no fabric is up (unit suite, no-node
dev), so these endpoints keep answering without a node.

POST   /rooms/{room}/sessions       — join a room (record presence + SLIM invite)
POST   /rooms/{room}/sessions/spawn — return the room's presence session
GET    /rooms/{room}/sessions       — list who is in a room
DELETE /rooms/{room}/sessions/{id}  — leave a room (SLIM remove)
"""

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.bus import bus, room_channel
from app.schemas import (
    CoordinationSessionRead,
    MessageType,
    ParticipantCreate,
    ParticipantListResponse,
    ParticipantRead,
)
from app.services import local_state, room_channels
from app.services.filesystem import (
    ensure_room_structure,
    get_room_dir,
    read_room_meta,
    room_exists,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/sessions", tags=["sessions"])


def _ensure_room(room_name: str) -> None:
    """Create the room directory on demand (coordination auto-join)."""
    if not room_exists(room_name):
        ensure_room_structure(get_room_dir(room_name))


@router.post("/spawn", response_model=dict, status_code=201)
async def spawn_session(room_name: str):
    """Return the room's presence session (a no-op shim spawn)."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    coord = local_state.get_or_create_session(room_name)
    return {
        "session_room": coord.display_name,
        "coordination_session_id": str(coord.id),
        "parent": room_name,
    }


@router.post("", response_model=ParticipantRead, status_code=201)
async def join_room(room_name: str, payload: ParticipantCreate):
    """Join a room — record the agent's presence. Idempotent per handle."""
    _ensure_room(room_name)
    coord = local_state.get_or_create_session(room_name)

    existing = local_state.find_participant(coord.id, payload.agent_handle)
    is_new = existing is None
    if is_new:
        context_files = (
            [cf.model_dump() for cf in payload.context_files] if payload.context_files else None
        )
        participant = local_state.StoredParticipant(
            id=local_state.participant_id(coord.id, payload.agent_handle),
            coordination_session_id=coord.id,
            agent_handle=payload.agent_handle,
            intent=payload.intent,
            context_files=context_files,
        )
        local_state.add_participant(coord.id, participant)
    else:
        logger.info("Re-join for handle=%s room=%s (re-inviting)", payload.agent_handle, room_name)
        participant = existing

    # Room = SLIM channel: make sure the channel exists, then invite the
    # agent onto it. Runs on EVERY join, not just the first: a connector announces
    # itself on each (re)connect, so a member dropped while its host slept (or on
    # any session close) is re-invited here and the durable inbox re-serves its
    # missed tail — no fresh @mention needed. The invite is idempotent (set-add +
    # an empty re-serve when already caught up) and fire-and-forget so its SLIM
    # handshake never blocks the join. Best-effort — no fabric = no live channel.
    meta = read_room_meta(room_name)
    workspace = meta.get("workspace_id") if meta else None
    await room_channels.manager.provision(room_name, workspace=workspace)
    room_channels.manager.invite_in_background(room_name, payload.agent_handle)

    # Persist a join message + fan it out on the FIRST join only, so a reconnecting
    # member re-inviting itself every wake doesn't spam the room's presence feed.
    if is_new:
        join_content = json.dumps(
            {
                "handle": payload.agent_handle,
                "intent": payload.intent,
                "session": coord.display_name,
            }
        )
        local_state.add_message(
            room_name,
            local_state.StoredMessage(
                room_name=room_name,
                sender_handle="CognitiveEngine",
                message_type=MessageType.COORDINATION_JOIN,
                content=join_content,
            ),
        )
        bus.publish(
            room_channel(room_name),
            {
                "room_name": room_name,
                "sender_handle": "CognitiveEngine",
                "message_type": MessageType.COORDINATION_JOIN,
                "content": json.dumps({"handle": payload.agent_handle, "intent": payload.intent}),
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    return ParticipantRead.model_validate(participant)


@router.get("/coordination", response_model=list[CoordinationSessionRead])
async def list_coordination_sessions(room_name: str):
    """List coordination sessions in a room (at most the one presence shim)."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    coord = local_state.get_session(room_name)
    if coord is None:
        return []
    return [CoordinationSessionRead.model_validate(coord)]


@router.get("", response_model=ParticipantListResponse)
async def list_sessions(room_name: str):
    """List agents participating in a room."""
    coord = local_state.get_session(room_name)
    if coord is None:
        if not room_exists(room_name):
            raise HTTPException(status_code=404, detail="Room or session not found")
        return ParticipantListResponse(participants=[], total=0)

    participants = local_state.list_participants(coord.id)
    # When a SLIM channel is live *and has members*, its membership is
    # authoritative for presence: surface only participants still on the channel.
    # local_state supplies the metadata (intent, context files) SLIM membership
    # doesn't carry. Without agent-side SLIM connectors, the moderator
    # can't invite HTTP joiners onto the channel, so SLIM membership is empty —
    # then (and when no channel is live at all) local_state is the source of truth.
    present = set(room_channels.manager.members(room_name))
    if present:
        participants = [p for p in participants if p.agent_handle in present]
    return ParticipantListResponse(
        participants=[ParticipantRead.model_validate(p) for p in participants],
        total=len(participants),
    )


@router.delete("/{session_id}", status_code=204)
async def leave_room(room_name: str, session_id: UUID):
    """Remove a participant (agent leaves the room + the SLIM channel)."""
    coord = local_state.get_session(room_name)
    if coord is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    # Resolve the handle before dropping the row, so we can remove it from SLIM.
    handle = next(
        (p.agent_handle for p in local_state.list_participants(coord.id) if p.id == session_id),
        None,
    )
    if not local_state.remove_participant(coord.id, session_id):
        raise HTTPException(status_code=404, detail="Participant not found")
    if handle is not None:
        await room_channels.manager.remove(room_name, handle)
