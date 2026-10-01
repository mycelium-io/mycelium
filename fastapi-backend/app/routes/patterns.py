# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Patterns API — design patterns as scenarios, loaded as a room.

GET  /patterns               the scenarios in the hub's pack
GET  /patterns/{name}        one, in full
POST /patterns/{name}/load   load one as a new room
POST /patterns/load          load a scenario the request carries (trusted callers)

A scenario is a room ready to run: a cast, some context, a task and the flow
that sets them working. Loading it is the writes any client can already make,
done in one call: the room, its engines, memories, the task and, with ``run``,
the summon that starts it. A scenario loads **paused** unless asked to run.

The hub offers only the pack its operator provides (``PATTERNS_DIR``); a caller
names a pattern in it and never a location, so a visitor cannot make the hub
fetch anything. Sending a scenario in the request is for a caller that holds its
own pack (``mycelium pattern use --from``) and is off when
``PATTERNS_ALLOW_INLINE`` is. ``PATTERNS_PERSONAS_ONLY`` refuses a scenario
that would start a worker.

Each write goes through the route that owns it (rooms, engines, memory, tasks,
messages), as ``routes/swarms.py`` does, so who may write is checked exactly as
the same calls made one at a time. The room name is claimed atomically, so two
callers loading the same pattern at once get two rooms, not one shared one. A
step that fails takes the room away again.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.routes.engines import EngineCreate, create_engine
from app.routes.memory import create_memories
from app.routes.messages import send_message
from app.routes.rooms import RESERVED_ROOMS, delete_room, make_room
from app.routes.tasks import TaskCreate
from app.routes.tasks import create_task as create_task_route
from app.schemas import (
    MemoryBatchCreate,
    MemoryCreate,
    MessageCreate,
    MessageType,
    RoomCreate,
)
from app.services import actor, patterns, protocols
from app.services.agent_registry import norm_handle
from app.services.filesystem import get_data_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patterns", tags=["patterns"])

#: Rooms a pattern may be loaded as: the pattern's name, then counted past.
MAX_NAME_ATTEMPTS = 99


class PatternMember(BaseModel):
    handle: str
    kind: str
    description: str = ""


class PatternSummary(BaseModel):
    """A scenario as a list shows it."""

    pattern: str
    title: str
    summary: str
    flow: str | None = Field(None, description="The flow it runs, if it runs one")
    roles: list[str] = Field(default_factory=list, description="The flow's roles, in order")
    members: list[PatternMember]


class PatternRead(PatternSummary):
    """A scenario in full: everything loading it would write."""

    scenario: dict[str, Any]
    flow_body: str | None = Field(None, description="The flow's YAML, when it brings its own")


class PatternList(BaseModel):
    patterns: list[PatternSummary]
    skipped: dict[str, str] = Field(
        default_factory=dict, description="Scenarios in the pack that did not load, and why"
    )


class PatternLoad(BaseModel):
    room: str | None = Field(
        None,
        description="Name for the new room. Default: the pattern's name, counted past if taken.",
    )
    private: bool = Field(False, description="List the room only for you")
    run: bool = Field(False, description="Start the flow once the room is loaded")
    dry_run: bool = Field(False, description="Say what would be written and write nothing")
    created_by: str | None = Field(None, description="Who is loading it")


class PatternLoadInline(PatternLoad):
    scenario: dict[str, Any] = Field(..., description="A scenario.yaml, parsed")
    flow: str | None = Field(None, description="The YAML of the flow flow_file names")


class PatternLoaded(BaseModel):
    room: str
    title: str
    members: list[str] = Field(description="Every handle registered in the room")
    memories: list[str] = Field(description="Keys written, in order")
    summon: str | None = Field(None, description="What starts the flow")
    key: str | None = Field(None, description="The task row (absent on a dry run)")
    episode: str | None = Field(None, description="The task's thread")
    ran: bool = False
    dry_run: bool = False


def _summary(loaded: patterns.Loaded) -> PatternSummary:
    s = loaded.scenario
    return PatternSummary(
        pattern=s.pattern,
        title=s.title,
        summary=s.summary,
        flow=s.summon.flow if s.summon else None,
        roles=loaded.protocol.roles if loaded.protocol else [],
        members=[
            PatternMember(handle=m.handle, kind=m.kind, description=m.description)
            for m in s.members
        ],
    )


def _refusal(exc: patterns.PatternInvalid) -> HTTPException:
    return HTTPException(status_code=422, detail="; ".join(exc.problems))


@router.get("", response_model=PatternList)
async def list_patterns() -> PatternList:
    """The scenarios in the hub's pack."""
    loaded, skipped = patterns.read_pack_all()
    return PatternList(patterns=[_summary(item) for item in loaded], skipped=skipped)


@router.get("/{name}", response_model=PatternRead)
async def get_pattern(name: str) -> PatternRead:
    """One scenario in full."""
    try:
        loaded = patterns.read_pack(name)
    except patterns.PatternNotFound as exc:
        raise HTTPException(status_code=404, detail=f"No pattern named {name!r}") from exc
    except patterns.PatternInvalid as exc:
        raise _refusal(exc) from exc
    return PatternRead(
        **_summary(loaded).model_dump(),
        scenario=loaded.scenario.model_dump(mode="json", exclude_none=True),
        flow_body=loaded.flow_body,
    )


@router.post("/load", response_model=PatternLoaded, status_code=201)
async def load_inline(payload: PatternLoadInline, request: Request) -> PatternLoaded:
    """Load a scenario the request carries, as a new room."""
    if not settings.PATTERNS_ALLOW_INLINE:
        raise HTTPException(
            status_code=403, detail="This hub loads only the patterns in its own pack"
        )
    try:
        loaded = patterns.parse(payload.scenario, payload.flow)
    except patterns.PatternInvalid as exc:
        raise _refusal(exc) from exc
    return await _load(loaded, payload, request)


@router.post("/{name}/load", response_model=PatternLoaded, status_code=201)
async def load_pattern(name: str, payload: PatternLoad, request: Request) -> PatternLoaded:
    """Load a pattern from the hub's pack as a new room."""
    try:
        loaded = patterns.read_pack(name)
    except patterns.PatternNotFound as exc:
        raise HTTPException(status_code=404, detail=f"No pattern named {name!r}") from exc
    except patterns.PatternInvalid as exc:
        raise _refusal(exc) from exc
    return await _load(loaded, payload, request)


def _claim_room(wanted: str, *, exact: bool) -> str:
    """Take a room name no one else has, in one step.

    Making the directory is the claim: it fails if the name is taken, so two
    callers cannot both be given it. Creating a room that exists is otherwise a
    quiet no-op, which would put two visitors in one room.
    """
    rooms = get_data_dir() / "rooms"
    rooms.mkdir(parents=True, exist_ok=True)
    for n in range(1, MAX_NAME_ATTEMPTS + 1):
        name = wanted if n == 1 else f"{wanted}-{n}"
        try:
            (rooms / name).mkdir()
        except FileExistsError:
            if exact:
                raise HTTPException(
                    status_code=409, detail=f"A room named {wanted!r} already exists"
                ) from None
            continue
        return name
    raise HTTPException(status_code=409, detail=f"No free room name starting {wanted!r}")


def _room_name(wanted: str) -> str:
    """The name as a room may be called, or a refusal saying why not."""
    try:
        name = RoomCreate(name=wanted).name
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=f"{wanted!r} cannot be a room name: {exc.errors()[0]['msg']}"
        ) from exc
    if name in RESERVED_ROOMS:
        raise HTTPException(status_code=400, detail=f"'{name}' is a reserved system name")
    return name


async def _load(loaded: patterns.Loaded, payload: PatternLoad, request: Request) -> PatternLoaded:
    scenario = loaded.scenario
    owner = norm_handle(actor.bind_optional_actor(request, payload.created_by, field="created_by"))
    if payload.private and not owner:
        raise HTTPException(
            status_code=422,
            detail="A private room needs an owner: who it's listed for. Say who you are first.",
        )
    me = owner or "web-ui"
    wanted = _room_name(payload.room or scenario.pattern)
    try:
        plan = patterns.build_plan(loaded, me)
    except patterns.PatternInvalid as exc:
        raise _refusal(exc) from exc

    if payload.dry_run:
        return PatternLoaded(
            room=wanted,
            title=scenario.room.title,
            members=[h for h, _, _ in plan.engines],
            memories=[m["key"] for m in plan.memories],
            summon=plan.summon,
            dry_run=True,
        )

    room = _claim_room(wanted, exact=payload.room is not None)
    doing = "create the room"
    try:
        await make_room(
            RoomCreate(
                name=room,
                title=scenario.room.title,
                description=scenario.room.description or None,
                is_public=not payload.private,
                owner=owner,
            ),
            owner,
            [],
        )
        for handle, kind, description in plan.engines:
            doing = f"register @{handle}"
            await create_engine(
                room,
                EngineCreate(handle=handle, kind=kind, description=description, created_by=me),
                request,
            )

        doing = "write the context and the members' notes"
        await create_memories(
            room,
            MemoryBatchCreate(items=[MemoryCreate(created_by=me, **m) for m in plan.memories]),
            request,
        )
        if scenario.summon is not None:
            _flow_is_listed(room, scenario.summon.flow, loaded.flow_body)

        doing = "file the task"
        row = await create_task_route(
            room, TaskCreate(title=scenario.task.title, handle=me), request
        )
        if scenario.task.body.strip():
            doing = "write the task"
            await create_memories(
                room,
                MemoryBatchCreate(
                    items=[
                        MemoryCreate(
                            key=row.key,
                            value=f"{scenario.task.title}\n\n{scenario.task.body.strip()}",
                            created_by=me,
                        )
                    ]
                ),
                request,
            )

        episode = str(row.episode or "")
        ran = False
        if payload.run and plan.summon is not None:
            doing = "start the flow"
            await send_message(
                room,
                MessageCreate(
                    sender_handle=me,
                    message_type=MessageType.BROADCAST,
                    content=plan.summon,
                    episode=episode,
                ),
                request,
            )
            ran = True
    except HTTPException as exc:
        await _take_away(room)
        raise HTTPException(
            status_code=exc.status_code, detail=f"Could not {doing}: {exc.detail}"
        ) from exc
    except Exception:
        await _take_away(room)
        logger.exception("pattern %s: could not %s in %s", scenario.pattern, doing, room)
        raise

    logger.info("pattern %s loaded as room %s by %s (ran=%s)", scenario.pattern, room, me, ran)
    return PatternLoaded(
        room=room,
        title=scenario.room.title,
        members=[h for h, _, _ in plan.engines],
        memories=[m["key"] for m in plan.memories],
        summon=plan.summon,
        key=row.key,
        episode=episode,
        ran=ran,
    )


def _flow_is_listed(room: str, flow: str, body: str | None) -> None:
    """The flow is in the room's list, and the pack's own beats a built-in.

    The hub does not check a flow when it is saved, so this is the last look
    before a summon would answer "I need a flow". The scenario was already
    parsed with the hub's own model; this catches the room not agreeing.
    """
    found = {p.name: source for p, source in protocols.catalogue(room)}
    if flow not in found:
        raise HTTPException(status_code=422, detail=f"the room does not list the flow {flow!r}")
    if body is not None and found[flow] != "room":
        raise HTTPException(
            status_code=422,
            detail=f"the room kept its built-in {flow!r} instead of the pack's flow",
        )


async def _take_away(room: str) -> None:
    """Remove a room that did not finish loading, so nothing half-made is left."""
    try:
        await delete_room(room)
    except Exception:
        logger.exception("pattern load: could not remove %s after a failure", room)
