# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Sessions API — tracks agent presence in rooms.

Reduced to a minimal in-memory presence shim (SLIM-native rebuild, Step 1). The
coordination-session machinery (join-window timer, MAS provisioning, CFN fan-in)
is gone; presence and rooms-as-channels move onto SLIM in Steps 3-4.

# TODO(step3): presence comes from SLIM membership; sessions become channels.

POST   /rooms/{room}/sessions       — join a room (record presence)
POST   /rooms/{room}/sessions/spawn — return the room's presence session
GET    /rooms/{room}/sessions       — list who is in a room
DELETE /rooms/{room}/sessions/{id}  — leave a room
"""

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.bus import bus, room_channel
from app.schemas import (
    CoordinationSessionRead,
    ParticipantCreate,
    ParticipantListResponse,
    ParticipantRead,
)
from app.services import local_state
from app.services.filesystem import ensure_room_structure, get_room_dir, room_exists

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
    if existing is not None:
        logger.info("Duplicate join for handle=%s room=%s", payload.agent_handle, room_name)
        return ParticipantRead.model_validate(existing)

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

    # Persist a join message and fan it out so watchers see the presence change.
    join_content = json.dumps(
        {"handle": payload.agent_handle, "intent": payload.intent, "session": coord.display_name}
    )
    local_state.add_message(
        room_name,
        local_state.StoredMessage(
            room_name=room_name,
            sender_handle="CognitiveEngine",
            message_type="coordination_join",
            content=join_content,
        ),
    )
    bus.publish(
        room_channel(room_name),
        {
            "room_name": room_name,
            "sender_handle": "CognitiveEngine",
            "message_type": "coordination_join",
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
    return ParticipantListResponse(
        participants=[ParticipantRead.model_validate(p) for p in participants],
        total=len(participants),
    )


@router.delete("/{session_id}", status_code=204)
async def leave_room(room_name: str, session_id: UUID):
    """Remove a participant (agent leaves the room)."""
    coord = local_state.get_session(room_name)
    if coord is None or not local_state.remove_participant(coord.id, session_id):
        raise HTTPException(status_code=404, detail="Participant not found")
