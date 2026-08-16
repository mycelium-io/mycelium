# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""GET /rooms/{room_name}/agents — structured agent manifest listing."""

import logging

from fastapi import APIRouter, HTTPException

from app.schemas import AgentRead
from app.services.agent_registry import room_agents
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/agents", tags=["agents"])


@router.get("", response_model=list[AgentRead])
async def list_agents(room_name: str) -> list[AgentRead]:
    """Return every agent registered in the room as structured JSON."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    return room_agents(room_name)
