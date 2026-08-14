# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
User + team endpoints — the human as a first-class principal.

The user store is global (people span rooms), unlike the room-scoped agent
manifests. Owner/team on a manifest point here; these endpoints surface the
records and the per-user / per-team budget roll-ups. Self-asserted: handles are
consistent, not cryptographic.

GET  /users            — list users, each with owned-agent + budget roll-up
POST /users            — create/upsert a user record
GET  /users/{handle}   — one user + the agents they own
GET  /teams            — teams rolled up from manifests + user memberships
"""

import logging

from fastapi import APIRouter, HTTPException

from app.schemas import (
    TeamListResponse,
    TeamRead,
    UserCreate,
    UserListResponse,
    UserRead,
)
from app.services import principals

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.get("/users", response_model=UserListResponse)
async def list_users():
    """List every registered user with their owned-agent budget roll-up."""
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


@router.get("/teams", response_model=TeamListResponse)
async def list_teams():
    """Teams rolled up from agent manifests and user memberships."""
    teams = [TeamRead(**t) for t in principals.list_teams()]
    return TeamListResponse(teams=teams, total=len(teams))
