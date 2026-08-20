# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Thread read/open API — a conversation scope inside a room.

A room is a flat broadcast transcript; past two participants it tangles. A thread
is the unit smaller than "the whole room" to follow, filter, and address. It is
**derived from the L9 causal DAG**, not stored — see :mod:`app.services.threads`
for the rules; these endpoints only serve them.

GET  /rooms/{room}/threads        — thread summaries, most recently active first
GET  /rooms/{room}/threads/{id}   — one thread plus its messages, oldest first
POST /rooms/{room}/threads        — open a thread (posts its root message)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.schemas import (
    MessageRead,
    ThreadCreate,
    ThreadDetailRead,
    ThreadListResponse,
    ThreadSummaryRead,
)
from app.services import actor, persister, principals, room_channels, threads
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/threads", tags=["threads"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _resolve(room_name: str, thread_id: str) -> threads.ThreadSummary:
    try:
        found = threads.resolve(room_name, thread_id)
    except threads.AmbiguousThread as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id!r} not found")
    return found


@router.get("", response_model=ThreadListResponse)
async def list_threads(room_name: str, limit: int = 50):
    """List a room's threads, most recently active first."""
    _require_room(room_name)
    return {"threads": [t.to_dict() for t in threads.room_threads(room_name, limit=limit)]}


@router.get("/{thread_id}", response_model=ThreadDetailRead)
async def get_thread(room_name: str, thread_id: str):
    """One thread and its messages, oldest first. ``thread_id`` may be a prefix."""
    _require_room(room_name)
    found = _resolve(room_name, thread_id)
    messages = [m for m in persister.room_conversation(room_name) if m.thread == found.id]
    messages.sort(key=lambda m: m.created_at)
    return {
        **found.to_dict(),
        "messages": [MessageRead.model_validate(m) for m in messages],
    }


@router.post("", response_model=ThreadSummaryRead, status_code=201)
async def open_thread(room_name: str, body: ThreadCreate, request: Request):
    """Open a thread by posting its root message; returns the new thread.

    A thread born from a reply needs nothing declared — the causal edge is the
    thread. Opening one *before* anyone has replied is the exception: the root
    message says so in its own L9 payload, so the thread exists (and can be
    addressed by id) from the moment it is created.
    """
    _require_room(room_name)
    sender = actor.bind_actor(request, body.sender_handle, field="sender_handle")
    reason = principals.post_rejection_reason(room_name, sender, allow_unregistered=True)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    result = await room_channels.manager.publish_human(
        room_name,
        sender=sender,
        text=body.title,
        payload_data={threads.THREAD_ROOT_KEY: True},
    )
    if result is None or not result.message_id:
        raise HTTPException(status_code=503, detail="No live channel for room")
    found = threads.resolve(room_name, result.message_id)
    if found is None:  # the root is in the transcript by now; be honest if it isn't
        raise HTTPException(status_code=503, detail="Thread root was not recorded")
    return found.to_dict()
