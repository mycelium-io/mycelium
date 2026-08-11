# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Plan API — projection over the ``plan/`` namespace of a room.

GET    /rooms/{room}/plan                  — files + parsed tasks
POST   /rooms/{room}/plan/tasks            — append a new ``- [ ]`` line
POST   /rooms/{room}/plan/tasks/{id}/toggle — flip / set checkbox
GET    /rooms/{room}/agent-context         — compact briefing for agent prompts

Plan files themselves are CRUD'd through the memory API (key ``plan/<slug>``).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.bus import bus, room_channel
from app.schemas import MessageType
from app.services import l9, local_state
from app.services import plan as plan_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/plan", tags=["plan"])

# Agent-context lives at /rooms/{room}/agent-context — a room-scoped resource,
# not a sub-path of /plan, so it gets its own router. It's the single endpoint
# every agent-dispatch path (mycelium-daemon, openclaw channel) hits to learn what
# the room is for; v1 returns the plan briefing, but the shape is built to
# grow (claimed tasks, recent activity) without callers changing.
agent_router = APIRouter(prefix="/rooms/{room_name}", tags=["plan"])


class TaskOut(BaseModel):
    id: str
    slug: str
    line: int
    text: str
    done: bool


class PlanFileOut(BaseModel):
    slug: str
    title: str
    content: str
    updated_at: str | None = None
    updated_by: str | None = None
    tasks: list[TaskOut]


class PlanOut(BaseModel):
    room: str
    title: str | None = None
    files: list[PlanFileOut]
    tasks: list[TaskOut]
    open_count: int
    done_count: int


class TitleUpdate(BaseModel):
    text: str = Field(..., max_length=500)
    updated_by: str = Field(default="frontend")


class TaskCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    slug: str = Field(default=plan_service.DEFAULT_TASK_FILE)


class TaskToggle(BaseModel):
    done: bool | None = None


def _task_to_out(t: plan_service.PlanTask) -> TaskOut:
    return TaskOut(id=t.id, slug=t.slug, line=t.line, text=t.text, done=t.done)


@router.get("", response_model=PlanOut)
async def get_plan(room_name: str) -> PlanOut:
    """Read every ``plan/*.md`` and return files + flat task list."""
    files, tasks = plan_service.load_plan(room_name)
    return PlanOut(
        room=room_name,
        title=plan_service.get_title(room_name),
        files=[
            PlanFileOut(
                slug=f.slug,
                title=f.title,
                content=f.content,
                updated_at=f.updated_at,
                updated_by=f.updated_by,
                tasks=[_task_to_out(t) for t in f.tasks],
            )
            for f in files
        ],
        tasks=[_task_to_out(t) for t in tasks],
        open_count=sum(1 for t in tasks if not t.done),
        done_count=sum(1 for t in tasks if t.done),
    )


def _emit_plan_updated(room_name: str, payload: dict) -> None:
    """Record a ``plan_updated`` message and publish it on the room channel.

    Used by the API-driven plan mutators (title set, task add, task toggle) so
    the chat-channel narrates plan edits the same way it narrates joins and
    consensus. Non-fatal: the mutation on disk has already succeeded by the time
    we reach this helper.
    """
    content = json.dumps(payload)
    local_state.add_message(
        room_name,
        local_state.StoredMessage(
            room_name=room_name,
            sender_handle=l9.SYSTEM_ACTOR_ID,
            message_type=MessageType.PLAN_UPDATED,
            content=content,
        ),
    )
    bus.publish(
        room_channel(room_name),
        {
            "room_name": room_name,
            "sender_handle": l9.SYSTEM_ACTOR_ID,
            "message_type": MessageType.PLAN_UPDATED,
            "content": content,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


@router.put("/title")
async def set_title(
    room_name: str,
    body: TitleUpdate,
) -> dict:
    title = plan_service.set_title(room_name, body.text, updated_by=body.updated_by)
    _emit_plan_updated(
        room_name,
        {"kind": "title_set", "title": title, "updated_by": body.updated_by},
    )
    return {"title": title}


@router.post("/tasks", response_model=TaskOut)
async def add_task(
    room_name: str,
    body: TaskCreate,
) -> TaskOut:
    task = plan_service.add_task(room_name, body.text, slug=body.slug)
    _emit_plan_updated(
        room_name,
        {
            "kind": "task_added",
            "slug": task.slug,
            "task_id": task.id,
            "text": task.text,
        },
    )
    return _task_to_out(task)


@router.post("/tasks/{task_id:path}/toggle", response_model=TaskOut)
async def toggle_task(
    room_name: str,
    task_id: str,
    body: TaskToggle | None = None,
) -> TaskOut:
    try:
        task = plan_service.toggle_task(room_name, task_id, done=body.done if body else None)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}") from e
    _emit_plan_updated(
        room_name,
        {
            "kind": "task_toggled",
            "slug": task.slug,
            "task_id": task.id,
            "text": task.text,
            "done": task.done,
        },
    )
    return _task_to_out(task)


class AgentContextOut(BaseModel):
    room: str
    handle: str | None = None
    generated_at: str  # ISO-8601 UTC — callers render staleness from this
    context: str | None = None  # None when the room has no plan


@agent_router.get("/agent-context", response_model=AgentContextOut)
async def get_agent_context(room_name: str, handle: str | None = None) -> AgentContextOut:
    """Compact room briefing injected into an agent's prompt on dispatch.

    Hot path — called on every ``@handle`` dispatch — so it stays a pure
    filesystem read with no DB round-trip. ``handle`` is accepted now and
    reserved for per-agent data (claimed tasks) once that lands; v1 ignores
    it and returns the room-wide plan briefing.
    """
    return AgentContextOut(
        room=room_name,
        handle=handle,
        generated_at=datetime.now(UTC).isoformat(),
        context=plan_service.agent_context(room_name),
    )
