# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Skills API — a promoted view over the ``skills/`` memory namespace (#617).

A skill is a memory under ``skills/`` (see ``app/services/skills.py``); these
routes are a thin, skill-shaped surface over the memory store — writes go through
the same upsert path (so they're indexed, linked, and broadcast like any memory),
reads pull the ``description`` from frontmatter. Room-scoped, like memory.

POST   /rooms/{room}/skills          — create or upsert a skill
GET    /rooms/{room}/skills          — list a room's skills
GET    /rooms/{room}/skills/{name}   — get one skill by name
DELETE /rooms/{room}/skills/{name}   — delete a skill
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from app.schemas import (
    MemoryBatchCreate,
    MemoryCreate,
    SkillCreate,
    SkillListResponse,
    SkillRead,
)
from app.services import actor, links, search_index, skills
from app.services.filesystem import (
    delete_memory_file,
    get_room_dir,
    recover_timestamps,
    room_exists,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/skills", tags=["skills"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _skill_read(room_name: str, name: str, meta: dict, body: str) -> SkillRead:
    """Build a SkillRead from a skill memory's frontmatter + body.

    A skill is a memory under ``skills/``, so its stamps are recovered the same
    way a memory's are — off the frontmatter, else the file — never off read
    time. ``get_skill`` reads the file directly, so without this it would report
    a different time on each request while ``list_skills`` (which goes through
    ``list_memory_files``) reported the recovered one.
    """
    created_at, updated_at = recover_timestamps(
        meta, get_room_dir(room_name) / f"{skills.skill_key(name)}.md"
    )
    return SkillRead(
        name=name,
        description=meta.get("description", ""),
        body=body,
        tags=meta.get("tags"),
        created_by=meta.get("created_by", "unknown"),
        updated_by=meta.get("updated_by"),
        version=meta.get("version", 1),
        created_at=created_at,
        updated_at=updated_at,
    )


@router.post("", response_model=SkillRead, status_code=201)
async def create_skill(room_name: str, payload: SkillCreate, request: Request) -> SkillRead:
    """Create or upsert a skill. Writes a ``skills/{name}`` memory (version bumps)."""
    # Break routes.memory ↔ routes.skills cycle.
    from app.routes.memory import upsert_memories

    _require_room(room_name)
    created_by = actor.bind_actor(request, payload.created_by, field="created_by")

    # Description rides in user-managed frontmatter (preserved on rewrites).
    item = MemoryCreate(
        key=skills.skill_key(payload.name),
        value={"text": payload.body},
        content_text=payload.body,
        tags=payload.tags,
        created_by=created_by,
        meta={**(payload.meta or {}), "description": payload.description},
    )
    result = await upsert_memories(room_name, MemoryBatchCreate(items=[item]))
    mem = result[0]
    return SkillRead(
        name=payload.name,
        description=payload.description,
        body=payload.body,
        tags=mem.tags,
        created_by=mem.created_by,
        updated_by=mem.updated_by,
        version=mem.version,
        created_at=mem.created_at,
        updated_at=mem.updated_at,
    )


@router.get("", response_model=SkillListResponse)
async def list_skills(room_name: str) -> SkillListResponse:
    """List a room's skills, newest-updated first."""
    _require_room(room_name)
    items = [
        _skill_read(room_name, name, meta, body)
        for name, meta, body in skills.list_room_skills(room_name)
    ]
    return SkillListResponse(skills=items, total=len(items))


@router.get("/{name}", response_model=SkillRead)
async def get_skill(room_name: str, name: str) -> SkillRead:
    """Get a specific skill by name."""
    _require_room(room_name)
    found = skills.read_room_skill(room_name, name)
    if found is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    meta, body = found
    return _skill_read(room_name, name, meta, body)


@router.delete("/{name}", status_code=204)
async def delete_skill(room_name: str, name: str) -> None:
    """Delete a skill by name. Removes the memory file and its index/link entries."""
    key = skills.skill_key(name)
    room_dir = get_room_dir(room_name)
    file_deleted = delete_memory_file(room_dir, key)
    index_deleted = search_index.remove(room_name, key)
    links.remove(room_name, key)
    if not file_deleted and not index_deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
