# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Skills API — a global, folder-based store of reusable, invokable skills.

Skills are markdown + YAML frontmatter (same grain as memory), but a distinct
**project-level** store: reusable across rooms, so global rather than room-scoped
(see ``app/services/skills.py``). This is the backing store for the chat
composer's ``/`` trigger and, later, agent-side invocation.

POST   /skills            — create or upsert a skill
GET    /skills            — list all skills
GET    /skills/{name}     — get one skill by name
DELETE /skills/{name}     — delete a skill
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.schemas import SkillCreate, SkillListResponse, SkillRead
from app.services import actor, skills

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])


def _skill_read(name: str, meta: dict, body: str) -> SkillRead:
    now = datetime.now(UTC)
    return SkillRead(
        name=meta.get("name", name),
        description=meta.get("description", ""),
        body=body,
        tags=meta.get("tags"),
        created_by=meta.get("created_by", "unknown"),
        updated_by=meta.get("updated_by"),
        version=meta.get("version", 1),
        created_at=meta.get("created_at", now),
        updated_at=meta.get("updated_at", now),
    )


@router.post("", response_model=SkillRead, status_code=201)
async def create_skill(payload: SkillCreate, request: Request) -> SkillRead:
    """Create or upsert a skill. Upsert bumps ``version`` (last-write-wins)."""
    created_by = actor.bind_actor(request, payload.created_by, field="created_by")
    meta, body = skills.write_skill(
        payload.name,
        payload.body,
        description=payload.description,
        created_by=created_by,
        tags=payload.tags,
        extra_meta=payload.meta,
    )
    return _skill_read(payload.name, meta, body)


@router.get("", response_model=SkillListResponse)
async def list_skills() -> SkillListResponse:
    """List all skills, newest-updated first."""
    items = [_skill_read(name, meta, body) for name, meta, body in skills.list_skills()]
    return SkillListResponse(skills=items, total=len(items))


@router.get("/{name}", response_model=SkillRead)
async def get_skill(name: str) -> SkillRead:
    """Get a specific skill by name."""
    found = skills.read_skill(name)
    if found is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    meta, body = found
    return _skill_read(name, meta, body)


@router.delete("/{name}", status_code=204)
async def delete_skill(name: str) -> None:
    """Delete a skill by name."""
    if not skills.delete_skill(name):
        raise HTTPException(status_code=404, detail="Skill not found")
