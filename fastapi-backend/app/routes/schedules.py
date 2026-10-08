# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Schedules API — an agent's recurring check-in, kept and fired by the hub.

See ``app/services/schedules.py``. Writing a schedule needs the right to act as
its owner (the same owner/allow_from rule ``await`` uses), since it decides when
that agent spends a turn.

GET    /rooms/{room}/schedules              — list (``?owner=`` narrows)
POST   /rooms/{room}/schedules              — create
GET    /rooms/{room}/schedules/{name}       — one, with its run history
PATCH  /rooms/{room}/schedules/{name}       — edit, pause, resume, renew
DELETE /rooms/{room}/schedules/{name}       — remove
POST   /rooms/{room}/schedules/{name}/run   — run it now
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import (
    ScheduleCreate,
    ScheduleListResponse,
    ScheduleRead,
    ScheduleRunRead,
    ScheduleRunRequest,
    ScheduleUpdate,
)
from app.services import actor, schedules
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/schedules", tags=["schedules"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _read(schedule: schedules.Schedule, now: datetime | None = None) -> ScheduleRead:
    now = now or datetime.now(UTC)
    data = schedule.model_dump()
    every_s = data.pop("every_s")
    return ScheduleRead.model_validate(
        {
            **data,
            "every": schedules.format_every(every_s) if every_s else None,
            "state": schedule.state(now),
        }
    )


def _refuse(err: schedules.ScheduleError) -> HTTPException:
    return HTTPException(status_code=err.status, detail=err.detail)


def _owned(request: Request, room_name: str, name: str) -> schedules.Schedule:
    try:
        schedule = schedules.get(room_name, name)
    except schedules.ScheduleError as err:
        raise _refuse(err) from err
    actor.authorize_handle(request, room_name, schedule.owner, field="owner")
    return schedule


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    room_name: str, owner: str | None = Query(None, description="Only this agent's")
) -> ScheduleListResponse:
    """Every schedule in the room, soonest next run first."""
    _require_room(room_name)
    now = datetime.now(UTC)
    want = (owner or "").lstrip("@").lower() or None
    items = [
        _read(s, now) for s in schedules.load(room_name).values() if want is None or s.owner == want
    ]
    far = datetime.max.replace(tzinfo=UTC)
    items.sort(key=lambda s: (s.state != "active", s.next_run or far, s.name))
    return ScheduleListResponse(schedules=items, total=len(items), checks=dict(schedules.CHECKS))


@router.post("", response_model=ScheduleRead, status_code=201)
async def create_schedule(
    room_name: str, payload: ScheduleCreate, request: Request
) -> ScheduleRead:
    """Set an agent a schedule. Held to the hub's minimum interval and per-agent cap."""
    _require_room(room_name)
    actor.authorize_handle(request, room_name, payload.owner, field="owner")
    created_by = actor.bind_optional_actor(request, payload.created_by, field="created_by")
    try:
        schedule = await schedules.create(
            room_name,
            name=payload.name,
            owner=payload.owner,
            every=payload.every,
            cron=payload.cron,
            prompt=payload.prompt,
            check=payload.check,
            task=payload.task,
            expires_in_days=payload.expires_in_days,
            created_by=created_by or payload.owner,
        )
    except schedules.ScheduleError as err:
        raise _refuse(err) from err
    return _read(schedule)


@router.get("/{name}", response_model=ScheduleRead)
async def get_schedule(room_name: str, name: str) -> ScheduleRead:
    """One schedule, with its recent runs (newest first)."""
    _require_room(room_name)
    try:
        return _read(schedules.get(room_name, name))
    except schedules.ScheduleError as err:
        raise _refuse(err) from err


@router.patch("/{name}", response_model=ScheduleRead)
async def update_schedule(
    room_name: str, name: str, payload: ScheduleUpdate, request: Request
) -> ScheduleRead:
    """Change a schedule: its timing, prompt, check or task; pause, resume or renew it."""
    _require_room(room_name)
    _owned(request, room_name, name)
    try:
        schedule = await schedules.update(
            room_name,
            name,
            every=payload.every,
            cron=payload.cron,
            prompt=payload.prompt,
            check=payload.check,
            task=payload.task,
            paused=payload.paused,
            renew=payload.renew,
            renew_days=payload.renew_days,
        )
    except schedules.ScheduleError as err:
        raise _refuse(err) from err
    return _read(schedule)


@router.delete("/{name}", status_code=204)
async def delete_schedule(room_name: str, name: str, request: Request) -> None:
    _require_room(room_name)
    _owned(request, room_name, name)
    try:
        await schedules.remove(room_name, name)
    except schedules.ScheduleError as err:
        raise _refuse(err) from err


@router.post("/{name}/run", response_model=ScheduleRunRead)
async def run_schedule(
    room_name: str, name: str, request: Request, payload: ScheduleRunRequest | None = None
) -> ScheduleRunRead:
    """Run a schedule now: its pre-check, then the wake if it found anything.

    Leaves its timetable alone. ``wake`` skips the pre-check.
    """
    _require_room(room_name)
    _owned(request, room_name, name)
    try:
        run = await schedules.fire(
            room_name, name, trigger="manual", wake=bool(payload and payload.wake)
        )
    except schedules.ScheduleError as err:
        raise _refuse(err) from err
    return ScheduleRunRead.model_validate(run.model_dump())
