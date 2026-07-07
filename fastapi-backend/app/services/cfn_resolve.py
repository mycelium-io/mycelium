# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Resolve CFN identifiers (workspace_id, mas_id) from client input, room
context, or backend settings.

Used by the knowledge ingest and CFN proxy routes to make these IDs
optional on the client side — the backend can fill them in from its own
config and database.
"""

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import CoordinationSession, Room

logger = logging.getLogger(__name__)


def resolve_workspace_id(client_value: str | None) -> str:
    """Return client_value if set, else settings.WORKSPACE_ID, else 400."""
    resolved = client_value or settings.WORKSPACE_ID
    if not resolved:
        raise HTTPException(
            status_code=400,
            detail=(
                "workspace_id not provided and WORKSPACE_ID is unset. "
                "Run `mycelium install` or set WORKSPACE_ID in your .env."
            ),
        )
    return resolved


async def resolve_mas_id(
    client_value: str | None,
    room_name: str | None,
    db: AsyncSession,
) -> str:
    """Resolve mas_id via: client value > DB lookup > settings > 400.

    ``room_name`` may be either a real room name or a legacy session display
    name (``{parent}:session:{short}``). For sessions, the mas_id lives on
    the CoordinationSession row, which inherits it from the parent room at
    spawn time. For real rooms, it lives on the Room row.
    """
    if client_value:
        return client_value

    if room_name:
        # Try resolving as a session display name first.
        if ":session:" in room_name:
            parent, _, short_id = room_name.partition(":session:")
            if parent and short_id:
                coord_result = await db.execute(
                    select(CoordinationSession).where(
                        CoordinationSession.parent_room_name == parent,
                        CoordinationSession.short_id == short_id,
                    )
                )
                coord = coord_result.scalar_one_or_none()
                if coord:
                    if coord.mas_id:
                        return coord.mas_id
                    # Coord session missing mas_id — fall back to parent room.
                    parent_result = await db.execute(select(Room).where(Room.name == parent))
                    parent_room = parent_result.scalar_one_or_none()
                    if parent_room and parent_room.mas_id:
                        return parent_room.mas_id

        result = await db.execute(select(Room).where(Room.name == room_name))
        room = result.scalar_one_or_none()
        if room is None:
            # Maybe it was a session display we couldn't resolve above.
            raise HTTPException(
                status_code=400,
                detail=f"room_name '{room_name}' not found — cannot resolve mas_id.",
            )
        if room.mas_id:
            return room.mas_id
        # Room exists but has no MAS of its own. Do NOT fall through to the
        # global settings.MAS_ID: cross-wiring a *named* room to an unrelated
        # (often stale) MAS silently misroutes its knowledge and spams 404s on
        # every write (the borrowed MAS may not exist under this workspace).
        # Fail cleanly so best-effort callers (knowledge fan-in) skip and real
        # callers get an actionable error. The global-MAS fallback below is
        # only for the no-room_name case (no room to attribute to).
        logger.debug("room '%s' exists but has no mas_id — not borrowing global MAS_ID", room_name)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Room '{room_name}' exists but has no mas_id configured. "
                f"Create it via `mycelium room create` (which provisions a MAS)."
            ),
        )

    if settings.MAS_ID:
        return settings.MAS_ID

    raise HTTPException(
        status_code=400,
        detail=(
            "Cannot resolve mas_id: none provided, no room_name supplied, "
            "and MAS_ID is unset. Run `mycelium install` or set MAS_ID in "
            "your .env, or pass room_name so the backend can look up the "
            "room's mas_id."
        ),
    )
