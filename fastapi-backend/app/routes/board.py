# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Coordination board API — the "Needs you" cockpit (issue #493).

GET  /rooms/{room}/board                     — the live projection (rows + members + counts)
POST /rooms/{room}/board/capture             — NL capture → a structured concern
POST /rooms/{room}/board/items/{id}/{verb}   — claim / block / resolve / promote / dismiss

The board projects over the event ledger, the compiled plan, and the live
episode (see ``services.board``); it holds no state of its own. The verbs are
the *same* vocabulary agents drive over the ledger, so human and agent triage
share one surface.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import board as board_service
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/board", tags=["board"])

Verb = Literal["claim", "block", "resolve", "promote", "dismiss"]


class BoardOwnerOut(BaseModel):
    handle: str
    kind: Literal["agent", "human"]
    present: bool = False


class BoardPrOut(BaseModel):
    number: int
    state: Literal["draft", "open", "merged"]


class BoardWorkOut(BaseModel):
    branch: str | None = None
    pr: BoardPrOut | None = None
    ci: Literal["green", "running", "failed"] | None = None


class BoardGithubOut(BaseModel):
    issue: int | None = None
    state: Literal["open", "closed"] | None = None


class BoardItemOut(BaseModel):
    id: str
    source: Literal["ledger", "plan", "episode"]
    kind: str
    state: str
    title: str
    detail: str | None = None
    owner: BoardOwnerOut | None = None
    work: BoardWorkOut | None = None
    github: BoardGithubOut | None = None
    choices: list[str] | None = None
    blocks: str | None = None
    waiting_on: str | None = None
    provenance: str | None = None
    age: str | None = None
    needs_you: bool = False
    note: str | None = None
    created_at: str | None = None


class BoardCounts(BaseModel):
    needs: int
    flight: int
    resolved: int


class BoardOut(BaseModel):
    room: str
    items: list[BoardItemOut]
    members: list[str]
    counts: BoardCounts


class CaptureBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    sender: str = Field(default="frontend")


class VerbBody(BaseModel):
    owner: str | None = None
    waiting_on: str | None = None
    issue: int | None = None


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


@router.get("", response_model=BoardOut)
async def get_board(room_name: str) -> BoardOut:
    """The live board: rows projected from the ledger, plan, and live episode."""
    _require_room(room_name)
    return BoardOut.model_validate(board_service.project_board(room_name))


@router.post("/capture", response_model=BoardItemOut, status_code=201)
async def capture(room_name: str, body: CaptureBody) -> BoardItemOut:
    """Natural-language capture → a structured, open concern on the board."""
    _require_room(room_name)
    item = board_service.capture_concern(room_name, body.text.strip(), sender=body.sender)
    return BoardItemOut.model_validate(item)


@router.post("/items/{item_id:path}/{verb}", status_code=204)
async def run_verb(room_name: str, item_id: str, verb: Verb, body: VerbBody | None = None) -> None:
    """Apply a triage verb to a board item (the same verbs agents drive)."""
    _require_room(room_name)
    body = body or VerbBody()
    try:
        board_service.apply_verb(
            room_name,
            item_id,
            verb,
            owner=body.owner,
            waiting_on=body.waiting_on,
            issue=body.issue,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Board item not found: {item_id}") from e
    except board_service.BoardError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
