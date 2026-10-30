# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Board API — the board as people read it, and what is waiting on a member.

GET /rooms/{room}/board          — the open epics as paths, and the other open tasks
GET /rooms/{room}/board/{key}    — one row as the board reads it, with its parts
GET /rooms/{room}/waiting?for=   — what is waiting on a member

All three are worked out on read (:mod:`app.services.board`,
:mod:`app.services.waiting`); nothing here writes. The app and the CLI draw
what these return rather than projecting epics themselves, so the two agree.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import refusals
from app.services import board, waiting
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}", tags=["board"])


class LatestLine(BaseModel):
    sender: str
    text: str
    at: str | None = None


class BoardPart(BaseModel):
    key: str
    title: str
    episode: str | None = None
    state: Literal["done", "blocked", "waiting", "working", "open"]
    holder: str | None = None
    assignee: str | None = None
    waiting_on: list[str] = Field(default_factory=list)
    blocked_by: str | None = None
    latest: LatestLine | None = Field(None, description="The newest message in its thread")
    parts: int = Field(0, description="How many rows are part of this one")
    parts_done: int = 0
    updated_at: str | None = None


class BoardEpic(BoardPart):
    lead: str | None = Field(None, description="Who holds it, else who wrote all its parts")
    done: int
    total: int
    steps: list[list[str]] = Field(
        default_factory=list,
        description="The parts' keys in path order; parts in one step run side by side",
    )
    path: list[BoardPart] = Field(default_factory=list)


class BoardRead(BaseModel):
    epics: list[BoardEpic]
    tasks: list[BoardPart] = Field(description="Open tasks that are part of no open epic")


class WaitingItem(BaseModel):
    kind: Literal["approve", "ask", "turn", "task"]
    key: str | None = Field(None, description="The task it's in; none for the room itself")
    title: str | None = None
    episode: str | None = None
    epic: str | None = None
    epic_title: str | None = None
    sender: str | None = Field(None, description="Who asked, or whose flow holds the floor")
    text: str | None = Field(None, description="The ask's first line, or the task's latest line")
    message_id: str | None = None
    at: str | None = None
    count: int = Field(1, description="Asks in the same thread, the newest shown")


class WaitingRead(BaseModel):
    handle: str
    items: list[WaitingItem]


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


@router.get("/board", response_model=BoardRead, responses=refusals(404))
async def read_board(room_name: str) -> BoardRead:
    """The room's open epics, each with its parts in path order, and its other open tasks."""
    _require_room(room_name)
    return BoardRead.model_validate(board.board(room_name, datetime.now(UTC)))


@router.get("/board/{key:path}", response_model=BoardEpic, responses=refusals(404))
async def read_board_row(room_name: str, key: str) -> BoardEpic:
    """One board row as the board reads it, settled or not, with its parts."""
    _require_room(room_name)
    found = board.show(room_name, key, datetime.now(UTC))
    if found is None:
        raise HTTPException(status_code=404, detail=f"No board row '{key}' in this room")
    return BoardEpic.model_validate(found)


@router.get("/waiting", response_model=WaitingRead, responses=refusals(404))
async def read_waiting(
    room_name: str,
    handle: str = Query(..., alias="for", description="The member to read for"),
) -> WaitingRead:
    """What is waiting on a member: asks it hasn't answered, a flow step whose
    floor it has, and the open tasks it holds that wait on nothing."""
    _require_room(room_name)
    items = waiting.waiting(room_name, handle, datetime.now(UTC))
    return WaitingRead(
        handle=handle.lstrip("@"), items=[WaitingItem.model_validate(i) for i in items]
    )
