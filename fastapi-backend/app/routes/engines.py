# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /rooms/{room_name}/engines — register a first-party cognition engine.

Engines (``aligner``, ``synthesizer``, ``hello``) are backend-owned: registration is purely
a manifest write with *no* machine-local side effects, so — unlike
``claude_code``/``cursor`` agents, which need a resident session and workspace
assets on the user's box — the web UI can invite one natively. The manifest lands
at ``agents/<handle>`` with ``adapter: engine``, exactly like the CLI's
``mycelium engine create``, so the summon seam (``_registered_engine_kind``) and
the ``GET .../agents`` listing pick it up like any other room citizen.
"""

import logging
import re

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.routes.memory import upsert_memories
from app.schemas import HANDLE_PATTERN, AgentRead, MemoryBatchCreate, MemoryCreate
from app.services import actor
from app.services.filesystem import get_room_dir, read_memory_file, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/engines", tags=["engines"])

# The engine kinds the backend knows how to run. Mirrors the CLI's
# ``mycelium.protocol.ENGINE_KINDS``; the summon seam self-selects by ``kind``.
ENGINE_KINDS = frozenset({"aligner", "hello", "synthesizer"})

_HANDLE_RE = re.compile(HANDLE_PATTERN)


class EngineCreate(BaseModel):
    """Request body to invite an engine into a room."""

    handle: str = Field(..., min_length=1, max_length=64)
    kind: str = Field("aligner", description="Which cognition engine to run.")
    description: str = ""
    allow_from: list[str] = Field(
        default_factory=list, description="Sender handles allowed to summon (empty = anyone)."
    )
    owner: str | None = None
    team: str | None = None
    created_by: str | None = Field(
        None, description="Who registered the engine; defaults to the web UI."
    )


def _norm(handle: str | None) -> str | None:
    if not handle:
        return None
    cleaned = handle.strip().lstrip("@").lower()
    return cleaned or None


@router.post("", response_model=AgentRead, status_code=201)
async def create_engine(room_name: str, payload: EngineCreate, request: Request) -> AgentRead:
    """Register an engine manifest in the room and return its structured view."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")

    # ``created_by`` is optional so an omitted field reads as "no claim" and a
    # verified token can fill it — the placeholder below is only for the
    # unauthenticated web UI, which has no identity to offer.
    registrar = actor.bind_optional_actor(request, payload.created_by, field="created_by")

    kind = payload.kind.strip().lower()
    if kind not in ENGINE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown engine kind {kind!r}; known: {sorted(ENGINE_KINDS)}",
        )

    handle = _norm(payload.handle)
    if not handle or not _HANDLE_RE.match(handle):
        raise HTTPException(
            status_code=422,
            detail="Handle must be a lowercase slug (a-z, 0-9, '-', '_') starting alphanumeric.",
        )

    key = f"agents/{handle}"
    room_dir = get_room_dir(room_name)
    if read_memory_file(room_dir, key) is not None:
        raise HTTPException(status_code=409, detail=f"@{handle} already exists in {room_name}")

    # Mirror the CLI manifest so the summon seam + agents listing read it
    # identically. ``handle`` is the memory key, so it stays out of the body.
    body = {
        "adapter": "engine",
        "kind": kind,
        "description": payload.description,
        "allow_from": [h for h in (_norm(a) for a in payload.allow_from) if h],
        "owner": _norm(payload.owner),
        "team": _norm(payload.team),
    }
    yaml_body = yaml.safe_dump(body, sort_keys=False, default_flow_style=False).strip()

    batch = MemoryBatchCreate(
        items=[
            MemoryCreate(
                key=key,
                value=yaml_body,
                created_by=registrar or "web-ui",
                # embed=False: a manifest is registry config, not room knowledge —
                # embedding it pollutes memory search + synthesis with roster noise.
                embed=False,
                tags=["agent-manifest"],
            )
        ]
    )
    await upsert_memories(room_name, batch)
    logger.info("room %s: registered engine @%s (kind=%s)", room_name, handle, kind)

    return AgentRead(
        handle=handle,
        adapter="engine",
        kind=kind,
        description=payload.description,
        owner=body["owner"],
        team=body["team"],
        allow_from=body["allow_from"],
    )
