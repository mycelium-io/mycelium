# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""GET /rooms/{room_name}/agents — structured agent manifest listing.

POST /rooms/{room_name}/agents/draft-notes — a member's notes, drafted by the
hub's Pi from the line a person typed about it, for the Add member dialog.

POST /rooms/{room_name}/agents/{handle}/rename — a new handle for an agent.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.schemas import AgentRead, AgentRename, AgentRenameRead, MessageCreate, MessageType
from app.services import actor, agent_rename, notes_draft
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


@router.post("/{handle}/rename", response_model=AgentRenameRead)
async def rename_agent(
    room_name: str, handle: str, payload: AgentRename, request: Request
) -> AgentRenameRead:
    """Give an agent a new handle, restart it under that handle, and tell the room.

    Its manifest and notes, the open rows it's meant for or holding, its
    presence and read positions move to the new handle (``agent_rename``), and
    nothing keeps the old one. A running agent can't take a new name from its
    environment, so when a connected machine has it in a herdr pane, that
    machine is asked to restart it there under the new handle (a ``rename``
    job, which asks the person at the machine the way a restart does). Then
    whoever renamed it says so in the room; everyone reads the same line. Past
    messages keep the handle they were signed with. Under a verified token,
    only someone who may act as the agent (its owner) may rename it.
    """
    old = norm_handle(handle) or ""
    new = norm_handle(payload.to) or ""
    actor.authorize_handle(request, room_name, old, field="handle")
    by = norm_handle(actor.bind_optional_actor(request, payload.by, field="by"))
    if not by:
        raise HTTPException(status_code=422, detail="Say who is renaming it (`by`).")
    # Looked up first: the machine reports it under the name it has now.
    target = agent_rename.restart_target(room_name, old)
    try:
        memories, rows = await agent_rename.rename(room_name, old, new, by=by)
    except agent_rename.RenameError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    job = None
    if target is not None:
        from app.services.runners import registry

        spec = {"room": room_name, "handle": old, "to": new}
        job = registry.enqueue(target, "rename", spec, created_by=by)
        logger.info("room %s: restart @%s as @%s on %s", room_name, old, new, target)

    from app.routes.messages import send_message  # lazy: routes import each other

    await send_message(
        room_name,
        MessageCreate(
            sender_handle=by,
            message_type=MessageType.BROADCAST,
            content=agent_rename.announcement(old, new),
        ),
        request,
    )
    return AgentRenameRead(
        handle=new,
        was=old,
        memories=memories,
        rows=rows,
        restart_runner=target if job else None,
        restart_job=job.id if job else None,
    )
