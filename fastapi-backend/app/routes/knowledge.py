# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a room's team learned (``services/knowledge.py``).

GET is the room's knowledge graph, or one task's lens on it (``?task=``), which
the app draws and ``mycelium memory graph`` prints. POST ``/settle`` marks a
memory as holding, so it's no longer open (``mycelium memory settle``).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import KnowledgeGraphRead, KnowledgeRead, KnowledgeSettle, refusals
from app.services import actor, knowledge
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/knowledge", tags=["knowledge"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


@router.get("", response_model=KnowledgeGraphRead, responses=refusals(404))
async def read_knowledge(
    room_name: str,
    task: str | None = Query(None, description="A task's key, to see the room through it"),
) -> KnowledgeGraphRead:
    """What the room's team learned, each piece with what it came from."""
    _require_room(room_name)
    # Building it reads every memory in the room; off the loop, so the hub keeps
    # answering while it does.
    graph = await asyncio.to_thread(knowledge.room_knowledge, room_name)
    if task:
        graph = knowledge.lens(graph, task)
    return KnowledgeGraphRead.model_validate(graph)


@router.post("/settle", response_model=KnowledgeRead, responses=refusals(404, 422))
async def settle_knowledge(
    room_name: str, payload: KnowledgeSettle, request: Request
) -> KnowledgeRead:
    """Mark a memory as holding: it's no longer open."""
    _require_room(room_name)
    by = actor.bind_delegated_actor(request, room_name, payload.handle, field="handle")
    try:
        node = await knowledge.settle(room_name, payload.key, by or "user")
    except LookupError as e:
        raise HTTPException(status_code=404, detail=f"No memory {payload.key}.") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return KnowledgeRead.model_validate(node)
