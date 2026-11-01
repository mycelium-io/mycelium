# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Subscriptions API: what an agent has asked to be woken for.

See ``app/services/subscriptions.py``. Subscribing needs the right to act as the
agent (the same owner/allow_from rule ``await`` uses), since it decides when
that agent spends a turn; an agent subscribes only itself, and nothing the hub
does by itself subscribes anyone.

GET    /rooms/{room}/subscriptions          — list (``?handle=`` narrows)
POST   /rooms/{room}/subscriptions          — subscribe
DELETE /rooms/{room}/subscriptions          — drop one (``?id=``) or all of a handle's
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import (
    WakeSubscriptionCreate,
    WakeSubscriptionListResponse,
    WakeSubscriptionRead,
    WakeSubscriptionsRemoved,
    refusals,
)
from app.services import actor, subscriptions
from app.services.agent_registry import norm_handle
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/subscriptions", tags=["subscriptions"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def read(sub: subscriptions.Subscription) -> WakeSubscriptionRead:
    """A subscription as the API gives it, with the line a person reads."""
    data = sub.model_dump(exclude={"ended_at"})
    return WakeSubscriptionRead.model_validate({**data, "describe": sub.describe()})


def _refuse(err: subscriptions.SubscriptionError) -> HTTPException:
    return HTTPException(status_code=err.status, detail=err.detail)


@router.get("", response_model=WakeSubscriptionListResponse, responses=refusals(404))
async def list_subscriptions(
    room_name: str, handle: str | None = Query(None, description="Only this agent's")
) -> WakeSubscriptionListResponse:
    """Every subscription in the room that hasn't ended, oldest first."""
    _require_room(room_name)
    now = datetime.now(UTC)
    want = norm_handle(handle) if handle else None
    items = [
        read(s)
        for s in subscriptions.load(room_name)
        if s.live_at(now) and (want is None or s.handle == want)
    ]
    return WakeSubscriptionListResponse(subscriptions=items, total=len(items))


@router.post(
    "", response_model=WakeSubscriptionRead, status_code=201, responses=refusals(403, 404, 422)
)
async def subscribe(
    room_name: str, payload: WakeSubscriptionCreate, request: Request
) -> WakeSubscriptionRead:
    """Subscribe an agent to a task, a kind of notice, a member or a search.
    The same subscription twice is one, renewed to the end asked this time."""
    _require_room(room_name)
    actor.authorize_handle(request, room_name, payload.handle)
    now = datetime.now(UTC)
    try:
        until, forever = subscriptions.parse_span(payload.span, now)
        sub = await subscriptions.add(
            room_name,
            payload.handle,
            payload.kind,
            payload.target,
            parts=payload.parts,
            task=payload.task or None,
            until=until,
            forever=forever,
            now=now,
        )
    except subscriptions.SubscriptionError as err:
        raise _refuse(err) from err
    return read(sub)


@router.delete("", response_model=WakeSubscriptionsRemoved, responses=refusals(403, 404))
async def unsubscribe(
    room_name: str,
    request: Request,
    handle: str = Query(..., description="The agent whose subscription goes"),
    id: str | None = Query(None, description="The one to drop; omit to drop all of them"),
) -> WakeSubscriptionsRemoved:
    """Drop one of an agent's subscriptions, or every one of them."""
    _require_room(room_name)
    actor.authorize_handle(request, room_name, handle)
    try:
        gone = await subscriptions.remove(room_name, handle, id)
    except subscriptions.SubscriptionError as err:
        raise _refuse(err) from err
    return WakeSubscriptionsRemoved(removed=[read(s) for s in gone])
