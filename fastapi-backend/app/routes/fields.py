# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Field API — the board's row actions, written down.

GET  /rooms/{room}/fields/{key}   — a row's writable fields right now
POST /rooms/{room}/fields         — put fields on a row

A sibling router rather than routes under ``/memory``, for the same reason
``leases`` and ``links`` sit beside it: the memory router ends in a
``{key:path}`` catch-all, so a suffix hung off it is an ordering bug waiting to
happen.

A board that changed a row's status in the browser and nowhere else was a
surface asserting something the room had never been told.  This is the write
that makes a row action real, and it is deliberately the *same* upsert a ``memory
set`` goes through — a human moving a card and an agent writing frontmatter are
one operation, so they leave one kind of trace.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import actor, fields
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/fields", tags=["fields"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _fail(error: fields.FieldError) -> HTTPException:
    return HTTPException(
        status_code=error.status, detail={"error": "field", "message": error.reason, **error.detail}
    )


class WriteBody(BaseModel):
    key: str = Field(..., description="Memory key of the row being written")
    handle: str = Field(..., description="Who is writing — recorded as the memory's author")
    fields: dict[str, object] = Field(
        ...,
        description=(
            "Frontmatter to merge onto the row. A null value clears its key. "
            "Assignment keys are refused: those move through /assignments."
        ),
    )


@router.post("")
async def write_fields(room_name: str, body: WriteBody, request: Request):
    """Put fields on a row, through the canonical memory upsert."""
    _require_room(room_name)
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
    try:
        return await fields.write(room_name, body.key, dict(body.fields), handle)
    except fields.FieldError as e:
        raise _fail(e) from e


@router.get("/{key:path}")
async def read_fields(room_name: str, key: str):
    """A row's writable fields, without changing anything."""
    _require_room(room_name)
    try:
        return fields.read(room_name, key)
    except fields.FieldError as e:
        raise _fail(e) from e
