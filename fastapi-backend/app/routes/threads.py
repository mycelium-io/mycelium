# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""/rooms/{room}/threads: start a thread from a message, and make a task of one.

A thread is a ``threads/`` memory naming the message it was started from
(``app/services/threads.py``). Starting one needs nothing but the message:
the thread is named after its first line and bound to a thread of its own at
the memory upsert, like any memory. Asking again for a message that already
has one answers with that one.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.schemas import MemoryRead, refusals
from app.services import actor, tasks, threads
from app.services.filesystem import (
    EPISODE_META,
    get_room_dir,
    list_memory_files,
    read_memory_file,
    room_exists,
)

router = APIRouter(prefix="/rooms/{room_name}/threads", tags=["threads"])

#: The relation a task made from a thread points back at it with.
THREAD_RELATION = "relates-to"


class ThreadCreate(BaseModel):
    from_: str = Field(
        ...,
        alias="from",
        min_length=1,
        max_length=128,
        description="The id of the message in the room's channel to start it from",
    )
    handle: str = Field(..., description="Who is starting it, recorded as its author")

    model_config = {"populate_by_name": True}


class ThreadTask(BaseModel):
    handle: str = Field(..., description="Who is filing it, recorded as the task's author")


def _read(room: str, key: str) -> MemoryRead:
    from app.routes.memory import _memory_read_from_file

    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No thread {key!r} in room {room!r}")
    meta, content = found
    return _memory_read_from_file(room, key, meta, content)


@router.post(
    "",
    response_model=MemoryRead,
    status_code=201,
    responses={200: {"model": MemoryRead}, **refusals(403, 404)},
)
async def start_thread(
    room_name: str, body: ThreadCreate, request: Request, response: Response
) -> MemoryRead:
    """Start a thread from a message in the room's channel, named after its first line.

    A message that already has a thread answers with it (200), so two people
    starting one at once land in the same conversation.
    """
    from app.routes.memory import upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
    async with _writing(room_name):
        if (existing := threads.thread_of_message(room_name, body.from_)) is not None:
            response.status_code = 200
            return _read(room_name, existing)
        message = threads.message_in_room(room_name, body.from_)
        if message is None:
            raise HTTPException(
                status_code=404,
                detail=f"No message {body.from_!r} in the channel of room {room_name!r} "
                "to start a thread from",
            )
        title = threads.title_of(message.content if isinstance(message.content, str) else "")
        written = await upsert_memories(
            room_name,
            MemoryBatchCreate(
                items=[
                    MemoryCreate(
                        key=threads.free_key(room_name, title),
                        value=title,
                        created_by=handle,
                        meta={threads.FROM_META: body.from_},
                    )
                ]
            ),
            system={EPISODE_META: tasks.mint_episode_urn(room_name)},
        )
        return written[0]


@router.post(
    "/{key:path}/task",
    response_model=MemoryRead,
    status_code=201,
    responses={200: {"model": MemoryRead}, **refusals(403, 404, 422)},
)
async def thread_task(
    room_name: str, key: str, body: ThreadTask, request: Request, response: Response
) -> MemoryRead:
    """File a task from a thread, pointing back at it (``relates-to``).

    The thread keeps its own conversation; the task gets one of its own. A
    thread that has a task already answers with it (200).
    """
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    if not threads.is_message_thread(key):
        raise HTTPException(status_code=422, detail=f"{key!r} is not a thread")
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
    thread = _read(room_name, key)
    async with _writing(room_name):
        for task_key, meta, _content in list_memory_files(
            get_room_dir(room_name), prefix=f"{tasks.WORK_NAMESPACE}/", limit=None
        ):
            related = meta.get(THREAD_RELATION)
            if related == key or (isinstance(related, list) and key in related):
                response.status_code = 200
                return _read(room_name, task_key)
        title = str(thread.value) if isinstance(thread.value, str) else key
        if isinstance(thread.value, dict):
            title = str(thread.value.get("text") or key).splitlines()[0]
        return await tasks.create_task(
            room_name,
            title,
            content=f"From the thread [[{key}]].",
            created_by=handle,
            # A task of the same name already on the board keeps its row.
            key=threads.free_key(room_name, title, namespace=tasks.WORK_NAMESPACE),
            meta={THREAD_RELATION: key},
        )


#: One writer at a time per room for what these routes check and then write
#: (is there a thread for this message, is this key free, does this thread
#: have a task), so two at once can't both pass the check and the second
#: overwrite the first.
_writers: dict[str, asyncio.Lock] = {}


def _writing(room: str) -> asyncio.Lock:
    return _writers.setdefault(room, asyncio.Lock())
