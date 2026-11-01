# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``GET /rooms/{room}/mentions/groups``: who ``@here`` and ``@all`` reach.

The composer asks before a message is sent, to show how many each group pings
and who they are, and to warn before a big send. It's the same answer a sent
message's groups are resolved to (``app.services.groups``), so who it shows is
who is woken.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import MentionGroups, refusals
from app.services import groups
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/mentions", tags=["messages"])


@router.get("/groups", response_model=MentionGroups, responses=refusals(404))
async def mention_groups(
    room_name: str,
    episode: str | None = Query(
        None, description="The thread being written in; without one, the room's channel"
    ),
    sender: str | None = Query(None, description="Who is writing, left out of every group"),
) -> MentionGroups:
    """Who ``@here`` and ``@all`` reach for ``sender`` writing in ``episode``."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail=f"Room '{room_name}' not found")
    reached = groups.members(room_name, episode=episode, sender=sender)
    return MentionGroups.model_validate(groups.as_wire(reached))
