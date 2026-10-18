# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Room settings API: a settings-shaped view over the ``settings/`` memories.

GET    /rooms/{room}/settings        every room setting, its value and where it comes from
PUT    /rooms/{room}/settings/{id}   set one for this room, with a reason
DELETE /rooms/{room}/settings/{id}   go back to the hub's value (or the default)

A room setting is a memory (``app/services/room_settings.py``), so a write here
is a memory write: through the same upsert, checked by the same table, indexed,
linked and broadcast like any memory. ``mycelium memory set settings/<id>``
does the same thing from the CLI.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.routes.memory import remove_memory, upsert_memories
from app.schemas import MemoryBatchCreate, MemoryCreate
from app.services import actor, room_settings
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/settings", tags=["room-settings"])


class RoomSettingRead(BaseModel):
    id: str
    kind: str = Field(description="bool, int or set")
    value: Any = Field(description="What the room runs with")
    source: str = Field(description="room (set here), hub (the hub's value) or default")
    hub_value: Any = Field(description="What the room would run with if it set nothing")
    options: list[str] = Field(default_factory=list, description="A set's choices")
    min: int | None = None
    max: int | None = Field(None, description="The hub's cap, for a setting a room may only lower")
    inherits: str | None = Field(None, description="The hub's config key this comes from")
    reason: str | None = Field(None, description="Why the room set it (the memory's body)")
    version: int | None = None
    updated_by: str | None = None
    updated_at: str | None = None


class RoomSettingWrite(BaseModel):
    value: Any
    reason: str = Field("", max_length=4000, description="Why, kept as the memory's body")
    by: str = Field(..., min_length=1, description="Who is changing it")
    base_version: int | None = Field(
        None, description="The version this change was made against; a newer one refuses it (409)"
    )


def _require(room_name: str, setting_id: str | None = None) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    if setting_id is not None and setting_id not in room_settings.BY_ID:
        raise HTTPException(status_code=404, detail=f"No room setting '{setting_id}'")


def _read(room_name: str, setting_id: str) -> RoomSettingRead:
    entry = next(e for e in room_settings.describe(room_name) if e["id"] == setting_id)
    return RoomSettingRead(**entry)


@router.get("", response_model=list[RoomSettingRead])
async def list_room_settings(room_name: str) -> list[RoomSettingRead]:
    """Every room setting, with the room's own value where it set one."""
    _require(room_name)
    return [RoomSettingRead(**e) for e in room_settings.describe(room_name)]


@router.put("/{setting_id}", response_model=RoomSettingRead)
async def set_room_setting(
    room_name: str, setting_id: str, payload: RoomSettingWrite, request: Request
) -> RoomSettingRead:
    """Set a room setting for this room, as a memory write at ``settings/<id>``."""
    _require(room_name, setting_id)
    by = actor.bind_delegated_actor(request, room_name, payload.by, field="by")
    reason = payload.reason.strip() or f"Set by @{by.lstrip('@')} from the settings page."
    await upsert_memories(
        room_name,
        MemoryBatchCreate(
            items=[
                MemoryCreate(
                    key=f"{room_settings.NAMESPACE}{setting_id}",
                    value=reason,
                    created_by=by,
                    base_version=payload.base_version,
                    meta={room_settings.VALUE_FIELD: payload.value},
                    embed=False,
                )
            ]
        ),
    )
    return _read(room_name, setting_id)


@router.delete("/{setting_id}", response_model=RoomSettingRead)
async def reset_room_setting(room_name: str, setting_id: str) -> RoomSettingRead:
    """Drop the room's own value, so it runs with the hub's (or the default) again."""
    _require(room_name, setting_id)
    try:
        await remove_memory(room_name, f"{room_settings.NAMESPACE}{setting_id}")
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    return _read(room_name, setting_id)
