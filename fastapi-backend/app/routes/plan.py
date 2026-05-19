# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Plan API — projection over the ``plan/`` namespace of a room.

GET    /rooms/{room}/plan                  — files + parsed tasks
POST   /rooms/{room}/plan/tasks            — append a new ``- [ ]`` line
POST   /rooms/{room}/plan/tasks/{id}/toggle — flip / set checkbox

Plan files themselves are CRUD'd through the memory API (key ``plan/<slug>``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import plan as plan_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/plan", tags=["plan"])


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


@router.put("/title")
async def set_title(room_name: str, body: TitleUpdate) -> dict:
    title = plan_service.set_title(room_name, body.text, updated_by=body.updated_by)
    return {"title": title}


@router.post("/tasks", response_model=TaskOut)
async def add_task(room_name: str, body: TaskCreate) -> TaskOut:
    task = plan_service.add_task(room_name, body.text, slug=body.slug)
    return _task_to_out(task)


@router.post("/tasks/{task_id:path}/toggle", response_model=TaskOut)
async def toggle_task(room_name: str, task_id: str, body: TaskToggle | None = None) -> TaskOut:
    try:
        task = plan_service.toggle_task(room_name, task_id, done=body.done if body else None)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}") from e
    return _task_to_out(task)
