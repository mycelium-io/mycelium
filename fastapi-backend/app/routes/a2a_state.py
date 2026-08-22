# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""GET /rooms/{room_name}/a2a/state — the bridge as the Network views see it.

The SLIM telemetry in ``/health`` cannot see the A2A bridge: an outbound call to
a remote agent and an inbound message to the room's own Agent Card both happen
off-channel. This route is the read that makes them legible next to SLIM traffic
— who is bridged (from the room's manifests), whether the room is discoverable
as an A2A agent (from the card it serves), and the recent exchanges either way
(from the in-process activity log).

Read-only and fail-soft: no bridged agents and no traffic is a valid answer, and
every counter is process-lifetime, so a restart honestly reads as zero.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.routes.a2a_server import build_room_card, room_card_url
from app.schemas import (
    A2aBridgedAgentRead,
    A2aBridgeState,
    A2aExchangeRead,
    A2aExposureRead,
)
from app.services import a2a_activity
from app.services.agent_registry import room_agents
from app.services.filesystem import room_exists

router = APIRouter(prefix="/rooms/{room_name}/a2a", tags=["a2a"])


@router.get("/state", response_model=A2aBridgeState)
async def a2a_state(room_name: str, request: Request, limit: int = 25) -> A2aBridgeState:
    """The room's A2A bridge state: bridged members, exposure, recent exchanges."""
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")

    agents = []
    for agent in room_agents(room_name):
        if agent.adapter != "a2a":
            continue
        stats = a2a_activity.agent_stats(room_name, agent.handle)
        agents.append(
            A2aBridgedAgentRead(
                handle=agent.handle,
                description=agent.description,
                card=agent.a2a_card,
                endpoint=agent.a2a_endpoint,
                skills=agent.a2a_skills,
                calls_ok=stats.calls_ok,
                calls_failed=stats.calls_failed,
                last_call_at=stats.last_call_at,
            )
        )

    card = build_room_card(room_name, request)
    rpc = next((i.url for i in card.supported_interfaces), "")
    totals = a2a_activity.totals(room_name)

    return A2aBridgeState(
        room=room_name,
        agents=agents,
        exposure=A2aExposureRead(
            card_url=room_card_url(room_name, request),
            rpc_url=rpc,
            skills=[s.id for s in card.skills],
            card_fetches=totals.card_fetches,
            messages=totals.inbound_messages,
            last_card_fetch_at=totals.last_card_fetch_at,
            last_message_at=totals.last_inbound_at,
        ),
        exchanges=[
            A2aExchangeRead(
                id=x.id,
                handle=x.handle,
                direction=x.direction,
                status=x.status,
                at=x.at,
                endpoint=x.endpoint,
                peer=x.peer,
                prompt=x.prompt,
                reply=x.reply,
                detail=x.detail,
                duration_ms=x.duration_ms,
            )
            for x in a2a_activity.recent(room_name, limit=limit)
        ],
        outbound_ok=totals.outbound_ok,
        outbound_failed=totals.outbound_failed,
    )
