# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /rooms/{room_name}/a2a-agents — register an external A2A agent.

An A2A agent is a remote Agent2Agent endpoint fielded as a room member. Like an
engine, registration is a backend-owned manifest write with no machine-local
side effects, so the web UI can invite one natively. Unlike an engine it has one
extra step: we resolve the remote Agent Card first, so a bad URL fails at
registration rather than at the first summon. The manifest lands at
``agents/<handle>`` with ``adapter: a2a`` plus the resolved card fields the seat
driver (#714) needs to call the remote agent.
"""

import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.schemas import HANDLE_PATTERN, AgentRead
from app.services import actor
from app.services.a2a_card import A2aCardError, resolve_card
from app.services.agent_registry import norm_handle, write_agent_manifest
from app.services.filesystem import get_room_dir, read_memory_file, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/a2a-agents", tags=["a2a"])

_HANDLE_RE = re.compile(HANDLE_PATTERN)


class A2aAgentCreate(BaseModel):
    """Request body to invite an external A2A agent into a room."""

    handle: str = Field(..., min_length=1, max_length=64)
    card: str = Field(..., description="Base URL serving the remote agent's Agent Card.")
    description: str = Field("", description="Overrides the card's description when set.")
    auth_env: str | None = Field(
        None,
        description=(
            "Name of a backend env var holding the bearer token for the remote agent. "
            "Only the var name is stored (in room memory); the secret stays in the env."
        ),
    )
    allow_from: list[str] = Field(
        default_factory=list, description="Sender handles allowed to summon (empty = anyone)."
    )
    owner: str | None = None
    team: str | None = None
    created_by: str | None = Field(
        None, description="Who registered the agent; defaults to the web UI."
    )


@router.post("", response_model=AgentRead, status_code=201)
async def create_a2a_agent(room_name: str, payload: A2aAgentCreate, request: Request) -> AgentRead:
    """Resolve the remote card, register the manifest, return the room view."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")

    registrar = actor.bind_optional_actor(request, payload.created_by, field="created_by")

    handle = norm_handle(payload.handle)
    if not handle or not _HANDLE_RE.match(handle):
        raise HTTPException(
            status_code=422,
            detail="Handle must be a lowercase slug (a-z, 0-9, '-', '_') starting alphanumeric.",
        )

    key = f"agents/{handle}"
    room_dir = get_room_dir(room_name)
    if read_memory_file(room_dir, key) is not None:
        raise HTTPException(status_code=409, detail=f"@{handle} already exists in {room_name}")

    # Resolve the card now so an unreachable or malformed endpoint is a clean 502
    # at registration, not a surprise when the aligner first addresses the seat.
    try:
        card = await resolve_card(payload.card)
    except A2aCardError as exc:
        raise HTTPException(status_code=502, detail=f"Could not resolve A2A card: {exc}") from exc

    description = payload.description.strip() or card.description

    body = {
        "adapter": "a2a",
        "description": description,
        "a2a_card": payload.card.strip().rstrip("/"),
        "a2a_endpoint": card.endpoint,
        "a2a_binding": card.protocol_binding,
        "a2a_card_path": card.card_path,
        "a2a_streaming": card.streaming,
        "a2a_skills": card.skill_ids,
        # Only the env var NAME lands in room memory; the token stays in the env.
        "a2a_auth_env": payload.auth_env.strip() if payload.auth_env else None,
        "allow_from": [h for h in (norm_handle(a) for a in payload.allow_from) if h],
        "owner": norm_handle(payload.owner),
        "team": norm_handle(payload.team),
    }
    await write_agent_manifest(room_name, handle, body, created_by=registrar or "web-ui")
    logger.info(
        "room %s: registered a2a agent @%s (%s, %d skills)",
        room_name,
        handle,
        card.endpoint,
        len(card.skills),
    )

    return AgentRead(
        handle=handle,
        adapter="a2a",
        description=description,
        owner=body["owner"],
        team=body["team"],
        allow_from=body["allow_from"],
        a2a_card=body["a2a_card"],
        a2a_endpoint=card.endpoint,
        a2a_skills=card.skill_ids,
    )
