# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Consent-gated invite endpoints — the human-in-the-room accept/decline surface
(Step 6, bible §12).

When a human ``@``-mentions an agent that is **not** on a room's channel, the
backend raises a :class:`~app.services.invites.PendingInvite` instead of inviting
straight away, and pushes a ``consent_request`` event onto the room's SSE stream.
These endpoints back the accept/decline prompt: only on ``accept`` does the
moderator invite (and, mid-episode, queue) the agent.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.services import room_channels
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/invites", tags=["invites"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


@router.get("")
async def list_invites(room_name: str):
    """List open (pending or queued) consent requests for a room."""
    _require_room(room_name)
    return {"invites": [inv.to_json() for inv in room_channels.manager.pending_invites(room_name)]}


@router.post("/{invite_id}/accept")
async def accept_invite(room_name: str, invite_id: str):
    """Accept a consent prompt — invite the agent (or queue it mid-episode)."""
    _require_room(room_name)
    invite = await room_channels.manager.accept_invite(invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return invite.to_json()


@router.post("/{invite_id}/decline")
async def decline_invite(room_name: str, invite_id: str):
    """Decline a consent prompt — the agent does not join."""
    _require_room(room_name)
    invite = room_channels.manager.decline_invite(invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return invite.to_json()
