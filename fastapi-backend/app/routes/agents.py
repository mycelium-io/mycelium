# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""GET /rooms/{room_name}/agents — structured agent manifest listing.

POST /rooms/{room_name}/agents/draft-notes — a member's notes, drafted by the
hub's Pi from the line a person typed about it, for the Add member dialog.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas import AgentRead
from app.services import notes_draft
from app.services.agent_registry import norm_handle, room_agents
from app.services.filesystem import read_room_meta, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/agents", tags=["agents"])


@router.get("", response_model=list[AgentRead])
async def list_agents(room_name: str) -> list[AgentRead]:
    """Return every agent registered in the room as structured JSON."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    return room_agents(room_name)


class NotesDraftRequest(BaseModel):
    """What a person said a member is for, and what kind of member it is."""

    brief: str = Field(min_length=1, max_length=notes_draft.MAX_BRIEF_CHARS)
    handle: str = ""
    kind: notes_draft.NotesKind = "agent"


class NotesDraftRead(BaseModel):
    notes: str


@router.post("/draft-notes", response_model=NotesDraftRead)
async def draft_notes(room_name: str, payload: NotesDraftRequest) -> NotesDraftRead:
    """Expand a short brief into a member's notes. Writes nothing to the room."""
    meta = read_room_meta(room_name)
    if meta is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if not payload.brief.strip():
        raise HTTPException(status_code=422, detail="Say what the agent is for first.")
    handle = norm_handle(payload.handle) or ""
    prompt = notes_draft.build_prompt(
        payload.brief,
        kind=payload.kind,
        handle=handle,
        room_title=meta.get("title") or room_name,
        teammates=[a.handle for a in room_agents(room_name)],
    )
    try:
        answer = await asyncio.wait_for(
            asyncio.to_thread(notes_draft.complete, prompt, room_name),
            timeout=notes_draft.TIMEOUT_S + 5.0,
        )
    except Exception as exc:
        logger.warning("draft-notes: no draft for %s", room_name, exc_info=True)
        raise HTTPException(
            status_code=502, detail="The hub's model couldn't write a draft. Try again."
        ) from exc
    notes = notes_draft.clean(answer or "")
    if not notes:
        raise HTTPException(status_code=502, detail="The hub's model returned an empty draft.")
    return NotesDraftRead(notes=notes)
