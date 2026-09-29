# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Sessions API — tracks agent presence in rooms.

Presence is handled by SLIM: joining a room invites the agent into the
room's SLIM group channel (backend = moderator), and — when a channel is live —
membership on that channel is authoritative for who is present. ``in_memory_store``
remains the metadata store (intent, context files) that SLIM membership doesn't
carry; it is also the sole fallback when no fabric is up (task suite, no-node
dev), so these endpoints keep answering without a node.

POST   /rooms/{room}/sessions       — join a room (record presence + SLIM invite)
POST   /rooms/{room}/sessions/spawn — return the room's presence session
GET    /rooms/{room}/sessions       — list who is in a room
DELETE /rooms/{room}/sessions/{id}  — leave a room (SLIM remove)
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.bus import bus, room_channel
from app.schemas import (
    CoordinationSessionRead,
    ParticipantCreate,
    ParticipantListResponse,
    ParticipantRead,
)
from app.services import actor, in_memory_store, l9, room_channels, tasks
from app.services.filesystem import (
    ensure_room_structure,
    get_room_dir,
    read_room_meta,
    room_exists,
)
from app.services.floor import Floor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/sessions", tags=["sessions"])


class HerdrAgentState(BaseModel):
    """One agent's live herdr state in a sync push."""

    status: str | None = Field(default=None, description="idle/working/blocked/done.")
    title: str | None = Field(
        default=None, description="herdr terminal title — the agent's current task."
    )


class HerdrPresenceBody(BaseModel):
    """The host-side ``mycelium herdr sync`` push: handle → herdr agent state.

    Each value may be a bare status string (simple form) or a
    :class:`HerdrAgentState` object carrying the status + current task title.
    """

    statuses: dict[str, str | HerdrAgentState] = Field(
        default_factory=dict,
        description="Map of agent handle → herdr state (status + optional task title).",
    )
    ttl_s: float | None = Field(
        default=None,
        description="Seconds an entry stays live without a refresh (default 90).",
    )


def _ensure_room(room_name: str) -> None:
    """Create the room directory on demand (coordination auto-join)."""
    if not room_exists(room_name):
        ensure_room_structure(get_room_dir(room_name))


@router.post("/spawn", response_model=dict, status_code=201)
async def spawn_session(room_name: str):
    """Return the room's presence session (a no-op shim spawn)."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    coord = in_memory_store.get_or_create_session(room_name)
    return {
        "session_room": coord.display_name,
        "coordination_session_id": str(coord.id),
        "parent": room_name,
    }


@router.post("", response_model=ParticipantRead, status_code=201)
async def join_room(room_name: str, payload: ParticipantCreate, request: Request):
    """Join a room — record the agent's presence. Idempotent per handle."""
    # Presence is a claim on a handle, same as draining its queue: registering as
    # someone else would put their name on the roster and pull their SLIM invite.
    # Authorized before the room is created, so a claim can't leave a room behind.
    actor.authorize_handle(request, room_name, payload.agent_handle, field="agent_handle")
    _ensure_room(room_name)
    coord = in_memory_store.get_or_create_session(room_name)

    existing = in_memory_store.find_participant(coord.id, payload.agent_handle)
    is_new = existing is None
    if is_new:
        context_files = (
            [cf.model_dump() for cf in payload.context_files] if payload.context_files else None
        )
        participant = in_memory_store.StoredParticipant(
            id=in_memory_store.participant_id(coord.id, payload.agent_handle),
            coordination_session_id=coord.id,
            agent_handle=payload.agent_handle,
            intent=payload.intent,
            context_files=context_files,
        )
        in_memory_store.add_participant(coord.id, participant)
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

    # Emit a coordination_join notice on the first join. Delegated to the manager
    # so all join paths (HTTP session, SLIM invite, await lease) share the same
    # dedup logic and the channel feed shows arrivals consistently.
    if is_new:
        room_channels.manager.announce_join(
            room_name, payload.agent_handle, intent=payload.intent or ""
        )

    return ParticipantRead.model_validate(participant)


@router.get("/coordination", response_model=list[CoordinationSessionRead])
async def list_coordination_sessions(room_name: str):
    """List coordination sessions in a room (at most the one presence shim)."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    coord = in_memory_store.get_session(room_name)
    if coord is None:
        return []
    return [CoordinationSessionRead.model_validate(coord)]


@router.get("", response_model=ParticipantListResponse)
async def list_sessions(room_name: str):
    """List agents participating in a room."""
    coord = in_memory_store.get_session(room_name)
    if coord is None:
        if not room_exists(room_name):
            raise HTTPException(status_code=404, detail="Room or session not found")
        return ParticipantListResponse(participants=[], total=0)

    participants = in_memory_store.list_participants(coord.id)
    # When a SLIM channel is live *and has members*, its membership is
    # authoritative for presence: surface only participants still on the channel.
    # in_memory_store supplies the metadata (intent, context files) SLIM membership
    # doesn't carry. Without agent-side SLIM connectors, the moderator
    # can't invite HTTP joiners onto the channel, so SLIM membership is empty —
    # then (and when no channel is live at all) in_memory_store is the source of truth.
    present = set(room_channels.manager.members(room_name))
    if present:
        participants = [p for p in participants if p.agent_handle in present]
    return ParticipantListResponse(
        participants=[ParticipantRead.model_validate(p) for p in participants],
        total=len(participants),
    )


@router.get("/members")
async def list_members(room_name: str):
    """Live presence: SLIM-socket members and server-held lease members.

    Returns every handle currently present in the room and how it's connected —
    ``"slim"`` for an active SLIM socket subscription, ``"lease"`` for a
    turn-based agent using ``await``/``reply`` (no persistent socket). Both
    kinds are first-class room members; the distinction surfaces liveness in the
    UI so you can tell a live connector from a polling agent at a glance.
    """
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    return {
        "members": [
            {
                "handle": h,
                "kind": info.kind,
                # Wall-clock ISO of the lease member's last poll; None for SLIM
                # members (a live socket is continuously present).
                "last_seen": (
                    datetime.fromtimestamp(info.last_seen, UTC).isoformat()
                    if info.last_seen is not None
                    else None
                ),
                # herdr live agent state (idle/working/blocked/…) when the handle
                # is mapped to a live herdr pane; None otherwise.
                "status": info.status,
                # True when a room mention is queued for this handle but held until
                # it goes idle (the hold-until-idle doorbell).
                "wake_pending": info.wake_pending,
                # herdr terminal title — the agent's current task, when herdr-present.
                "title": info.title,
            }
            for h, info in sorted(room_channels.manager.presence(room_name).items())
        ],
        # Threads whose floor a run of backend code holds right now: who holds
        # it and who it was given to. A thread fact rather than a presence one,
        # so a member the floor was given to shows it whether or not it is
        # present — a persona engine is never in ``members`` and still speaks.
        "floors": [
            _floor_entry(room_name, floor) for floor in room_channels.manager.floors_of(room_name)
        ],
    }


def _floor_entry(room_name: str, floor: Floor) -> dict[str, object]:
    """One held floor, named by the task its thread belongs to.

    A badge says the task's name rather than the thread's id; ``key`` and
    ``title`` are both ``None`` for a thread no row carries.
    """
    row = tasks.row_of_episode(room_name, floor.episode)
    return {
        "thread": floor.episode.rsplit(":", 1)[-1],
        "episode": floor.episode,
        "key": row[0] if row else None,
        "title": row[1] if row else None,
        "holder": floor.holder,
        "speakers": sorted(floor.speakers),
    }


@router.post("/herdr-presence", status_code=204)
async def push_herdr_presence(room_name: str, body: HerdrPresenceBody):
    """Overlay herdr liveness for a room (the ``mycelium herdr sync`` bridge's push).

    The backend runs containerized and can't see the host's herdr socket, so the
    host-side bridge polls ``herdr agent list`` and pushes the current per-handle
    state here. This is a presence/UI surface only — it never enters the mediator
    roster. Entries lapse on their TTL, so a stopped bridge / closed pane clears
    itself without an explicit delete.
    """
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    normalized: dict[str, str | dict] = {
        h: ({"status": v.status, "title": v.title} if isinstance(v, HerdrAgentState) else v)
        for h, v in body.statuses.items()
    }
    room_channels.manager.set_herdr_presence(
        room_name, normalized, ttl_s=body.ttl_s if body.ttl_s else 90.0
    )


@router.get("/herdr-wakes")
async def drain_herdr_wakes(room_name: str):
    """Drain pending herdr wake requests for a room (the sync bridge polls this).

    Returns and clears the queue the backend filled when a tag mentioned a
    herdr-present-but-not-joined handle. The bridge — the only actor that can
    reach the host's herdr socket — then runs the actual ``herdr agent prompt``.
    """
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    return {"wakes": room_channels.manager.drain_herdr_wakes(room_name)}


@router.delete("/{session_id}", status_code=204)
async def leave_room(room_name: str, session_id: UUID):
    """Remove a participant (agent leaves the room + the SLIM channel)."""
    coord = in_memory_store.get_session(room_name)
    if coord is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    # Resolve the handle before dropping the row, so we can remove it from SLIM.
    handle = next(
        (p.agent_handle for p in in_memory_store.list_participants(coord.id) if p.id == session_id),
        None,
    )
    if not in_memory_store.remove_participant(coord.id, session_id):
        raise HTTPException(status_code=404, detail="Participant not found")
    if handle is not None:
        await room_channels.manager.remove(room_name, handle)
        # Mirror the join event so the room's agent roster updates live on leave.
        bus.publish(
            room_channel(room_name),
            {
                "type": "coordination_leave",
                "room_name": room_name,
                "agent_handle": handle,
                "sender_handle": l9.SYSTEM_ACTOR_ID,
                "message_type": "coordination_leave",
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
