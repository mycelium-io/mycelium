# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Asks API: an agent asks a person to decide, and the person answers.

POST /rooms/{room}/asks              — ask (``mycelium ask --approve``)
POST /rooms/{room}/asks/{id}/answer  — approve or decline, as the person asked

The ask and the answer are messages in the task's thread
(:mod:`app.services.approvals`); these routes are the only way to write either,
so the fields the app draws are always ones the hub checked.
"""

from fastapi import APIRouter, HTTPException, Request

from app.schemas import (
    Ask,
    AskAnswer,
    AskAnswerCreate,
    AskAnswered,
    AskCreate,
    AskPosted,
    refusals,
)
from app.services import actor, approvals, principals, room_people
from app.services.filesystem import room_exists
from app.services.persister import read_id, record_episode

router = APIRouter(prefix="/rooms/{room_name}/asks", tags=["asks"])


def _room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail=f"Room '{room_name}' not found")


@router.post(
    "", response_model=AskPosted, status_code=201, responses=refusals(403, 404, 409, 422, 503)
)
async def create_ask(room_name: str, body: AskCreate, request: Request) -> AskPosted:
    """Ask a person to decide something, in a task's thread."""
    from app.routes.participate import _last_tick

    _room(room_name)
    handle = actor.bind_delegated_actor(request, room_name, body.handle, field="handle")
    reason = principals.post_rejection_reason(room_name, handle, allow_unregistered=False)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    last = (_last_tick.get((room_name, handle)) or {}).get("l9") or {}
    recent = ((last.get("header") or {}).get("message") or {}).get("episode")
    try:
        ask, record, task = await approvals.create(
            room_name,
            handle,
            question=body.question,
            kind=body.kind,
            to=body.to,
            task=body.task,
            recent_episode=recent if isinstance(recent, str) else None,
            facts={fact: getattr(body, fact) for fact in approvals.FACTS},
        )
    except approvals.Refused as refused:
        raise HTTPException(status_code=refused.status, detail=refused.detail) from None
    return AskPosted(
        room=room_name,
        task=task,
        episode=record_episode(record),
        message_id=str(read_id(record)),
        ask=Ask.model_validate(ask),
    )


@router.post(
    "/{ask_id}/answer",
    response_model=AskAnswered,
    responses=refusals(403, 404, 409, 422, 503),
)
async def answer_ask(
    room_name: str, ask_id: str, body: AskAnswerCreate, request: Request
) -> AskAnswered:
    """Approve or decline an ask. Only the person asked may, and only once."""
    _room(room_name)
    by = actor.bind_delegated_actor(request, room_name, body.by, field="by")
    try:
        ask, answer, record = await approvals.answer(
            room_name, ask_id, decision=body.decision, by=by, reason=body.reason
        )
    except approvals.Refused as refused:
        raise HTTPException(status_code=refused.status, detail=refused.detail) from None
    room_people.joined_by_message(room_name, by)
    return AskAnswered(
        room=room_name,
        message_id=str(read_id(record)),
        ask=Ask.model_validate(ask),
        answer=AskAnswer.model_validate(answer),
    )
