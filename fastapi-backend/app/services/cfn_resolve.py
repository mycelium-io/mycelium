# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

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
from app.models import Room

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
    """Resolve mas_id via: client value > room DB lookup > settings > 400.

    When room_name is provided, looks up the Room row and reads its mas_id.
    If the room is a session sub-room (has parent_namespace), walks up to
    the parent namespace which owns the MAS.
    """
    if client_value:
        return client_value

    if room_name:
        result = await db.execute(select(Room).where(Room.name == room_name))
        room = result.scalar_one_or_none()
        if room is None:
            raise HTTPException(
                status_code=400,
                detail=f"room_name '{room_name}' not found — cannot resolve mas_id.",
            )
        if room.mas_id:
            return room.mas_id
        # Session sub-rooms inherit mas_id from their parent namespace
        if room.parent_namespace:
            parent_result = await db.execute(select(Room).where(Room.name == room.parent_namespace))
            parent = parent_result.scalar_one_or_none()
            if parent and parent.mas_id:
                return parent.mas_id
        logger.warning("room '%s' exists but has no mas_id (and no parent with one)", room_name)
        if not settings.MAS_ID:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Room '{room_name}' exists but has no mas_id configured "
                    f"(and no parent namespace with one). Either create the room "
                    f"via `mycelium room create` (which provisions a MAS), or set "
                    f"MAS_ID in your backend .env as a fallback."
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
