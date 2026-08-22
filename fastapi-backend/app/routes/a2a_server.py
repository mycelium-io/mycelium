# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Expose a room *as* an A2A agent (epic #719, #716) — the inbound mirror.

Where ``a2a_bridge`` lets a room call *out* to a remote A2A agent, this lets an
external A2A client call *in*: it discovers a room's Agent Card and sends it a
message, which lands in the room like any other post. Card serialization and the
JSON-RPC wire are the SDK's (``agent_card_to_dict`` + ``JsonRpcDispatcher``), so
the bytes are correct by construction; we only supply the room-specific card and
an :class:`AgentExecutor` that injects the message into the room.

Per-room: each room is its own A2A agent at ``/rooms/{room}/…``. The card + a
throwaway request handler are built per request, so a new room needs no route
wiring.

Scope (v1): ``message/send`` delivers the message into the room and returns an
ack. If the message ``@``-mentions a room agent, normal room dynamics take over
(including the outbound a2a responder) — this endpoint just doesn't block on that
async reply. Returning the room's reply synchronously is a follow-up.
"""

from __future__ import annotations

import logging
import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
)
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, Response

from app.services import a2a_activity, l9
from app.services.filesystem import room_exists
from app.services.l9_slim import serialize_content
from app.services.skills import list_room_skills

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}", tags=["a2a"])

_GUEST_HANDLE = "a2a-guest"


def build_room_card(room: str, request: Request) -> AgentCard:
    """The A2A Agent Card for a room, skills drawn from its ``skills/`` namespace."""
    base = str(request.base_url).rstrip("/")
    rpc_url = f"{base}/api/rooms/{room}/a2a"
    skills = [
        AgentSkill(
            id=name,
            name=str(meta.get("title") or name),
            description=str(meta.get("description") or ""),
        )
        for name, meta, _body in list_room_skills(room)
    ]
    return AgentCard(
        name=room,
        description=f"Mycelium coordination room '{room}'. Post a message to reach its members.",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=skills,
        supported_interfaces=[AgentInterface(url=rpc_url, protocol_binding="JSONRPC")],
    )


def room_card_url(room: str, request: Request) -> str:
    """Where this room's Agent Card is served — the discovery URL clients fetch."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/rooms/{room}/.well-known/agent-card.json"


async def _inject_into_room(room: str, text: str) -> str:
    """Post ``text`` into the room as the a2a guest; return an ack line."""
    from app.services.room_channels import manager

    managed = manager.get(room)
    if managed is None:
        ack = f"Room '{room}' is not active."
        a2a_activity.record_inbound(
            room, handle=_GUEST_HANDLE, status="error", prompt=text, detail=ack
        )
        return ack
    env = l9.build_envelope(
        kind=l9.Kind.exchange,
        episode=l9.episode_urn(room, "live"),
        sender=_GUEST_HANDLE,
        sender_role="agent",
        topic=l9.topic_urn(room),
        payload_type="message",
    )
    content = serialize_content(env, extra={"content": text})
    try:
        await managed.channel.send(env, extra={"content": text})
    except Exception:
        logger.warning("a2a-server: failed to broadcast inbound message to room %s", room)
    if managed.persister is not None:
        managed.persister.ingest_local(env, content, list_write=True)
    ack = f"Delivered to room '{room}'."
    a2a_activity.record_inbound(room, handle=_GUEST_HANDLE, status="ok", prompt=text, reply=ack)
    return ack


class _RoomAgentExecutor(AgentExecutor):
    """Deliver an inbound A2A message into a room and ack it."""

    def __init__(self, room: str) -> None:
        self._room = room

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = (context.get_user_input() or "").strip()
        ack = (
            await _inject_into_room(self._room, text)
            if text
            else "Empty message; nothing delivered."
        )
        await event_queue.enqueue_event(
            Message(
                message_id=uuid.uuid4().hex,
                role=Role.ROLE_AGENT,
                parts=[Part(text=ack)],
                context_id=context.context_id or "",
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # message/send is fire-and-ack; there's no long-running task to cancel.
        return


@router.get("/.well-known/agent-card.json")
async def a2a_agent_card(room_name: str, request: Request) -> Response:
    """Serve the room's A2A Agent Card (the discovery half)."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    card = build_room_card(room_name, request)
    a2a_activity.record_card_fetch(room_name)
    return JSONResponse(agent_card_to_dict(card))


@router.post("/a2a")
async def a2a_rpc(room_name: str, request: Request) -> Response:
    """Handle A2A JSON-RPC (``message/send``) for the room."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")
    card = build_room_card(room_name, request)
    handler = DefaultRequestHandler(_RoomAgentExecutor(room_name), InMemoryTaskStore(), card)
    dispatcher = JsonRpcDispatcher(handler, enable_v0_3_compat=True)
    return await dispatcher.handle_requests(request)
