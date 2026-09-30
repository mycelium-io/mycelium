# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Protocols API: the flows a room's conductor can run.

GET /rooms/{room}/protocols — the room's own ``protocols/<name>`` specs, then
the built-ins it doesn't reshape, each with its description and the roles a
summon binds in order. It is what the composer reads to help write
``@conductor <flow> @a @b: …``; the conductor itself loads the same specs.
"""

from fastapi import APIRouter, HTTPException

from app.schemas import ProtocolSummary
from app.services import protocols
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/protocols", tags=["protocols"])


@router.get("", response_model=list[ProtocolSummary])
async def list_protocols(room_name: str) -> list[ProtocolSummary]:
    """The flows a summon in this room can name."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    return [
        ProtocolSummary(name=p.name, description=p.description, roles=p.roles, source=source)
        for p, source in protocols.catalogue(room_name)
    ]
