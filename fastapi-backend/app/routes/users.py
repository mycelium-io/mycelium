# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
User + team endpoints — the human as a first-class principal.

The user store is global (people span rooms), unlike the room-scoped agent
manifests. Owner/team on a manifest point here; these endpoints surface the
records and the per-user / per-team owned-agent roll-ups. Self-asserted:
handles are consistent, not cryptographic.

GET  /users            — list users, each with an owned-agent roll-up
POST /users            — create/upsert a user record
GET  /users/{handle}   — one user + the agents they own
GET  /users/{handle}/room-folders — how they organize their rooms list
PUT  /users/{handle}/room-folders — replace it
GET  /teams            — teams rolled up from manifests + user memberships
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from app.schemas import (
    RoomFolders,
    TeamListResponse,
    TeamRead,
    UserCreate,
    UserListResponse,
    UserRead,
)
from app.services import actor, principals, room_folders

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.get("/users", response_model=UserListResponse)
async def list_users():
    """List every registered user with their owned-agent roll-up."""
    users = [UserRead(**u) for u in principals.list_users_with_rollup()]
    return UserListResponse(users=users, total=len(users))


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(payload: UserCreate):
    """Create or upsert a user in the global store."""
    principals.write_user(payload.model_dump())
    user = principals.user_with_rollup(payload.handle)
    if user is None:  # pragma: no cover — just written
        raise HTTPException(status_code=500, detail="user write did not persist")
    return UserRead(**user)


@router.get("/users/{handle}", response_model=UserRead)
async def get_user(handle: str):
    """One user record plus the agents they own."""
    user = principals.user_with_rollup(handle)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserRead(**user)


def _own_handle(request: Request, handle: str) -> str:
    """The handle whose folders these are. On a gated hub, only your own: a
    person's layout is theirs to read and write, like their queue."""
    return actor.bind_actor(request, handle, field="handle")


@router.get("/users/{handle}/room-folders", response_model=RoomFolders)
async def get_room_folders(handle: str, request: Request) -> RoomFolders:
    """How this person has organized their rooms list. None yet reads as empty."""
    return room_folders.load(_own_handle(request, handle))


@router.put("/users/{handle}/room-folders", response_model=RoomFolders)
async def put_room_folders(handle: str, payload: RoomFolders, request: Request) -> RoomFolders:
    """Replace this person's folders with ``payload`` (the whole layout)."""
    try:
        return room_folders.save(_own_handle(request, handle), payload)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.get("/teams", response_model=TeamListResponse)
async def list_teams():
    """Teams rolled up from agent manifests and user memberships."""
    teams = [TeamRead(**t) for t in principals.list_teams()]
    return TeamListResponse(teams=teams, total=len(teams))
