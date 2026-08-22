# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A2A bridge state for the Network views (#739).

Covers what the GUI pane and ``mycelium network`` read: bridged members with
their endpoint + skills, the room's own exposure as an A2A agent, and the
exchanges recorded either way.
"""

import pytest
import yaml

from app.services import a2a_activity
from app.services.filesystem import get_room_dir, write_memory_file

_ROOM = "portfolio"
_STATE = f"/api/rooms/{_ROOM}/a2a/state"


async def _make_room(client, name: str = _ROOM) -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201)


def _register_a2a(handle: str = "researcher", *, room: str = _ROOM) -> None:
    manifest = {
        "adapter": "a2a",
        "description": "does research",
        "a2a_card": "https://remote.example",
        "a2a_endpoint": "https://remote.example/a2a",
        "a2a_skills": ["research", "summarize"],
    }
    write_memory_file(
        get_room_dir(room), f"agents/{handle}", yaml.safe_dump(manifest), created_by="web-ui"
    )


def _register_resident(handle: str = "avery-agent") -> None:
    body = yaml.safe_dump({"adapter": "claude_code", "description": "resident"})
    write_memory_file(get_room_dir(_ROOM), f"agents/{handle}", body, created_by="web-ui")


@pytest.mark.asyncio
async def test_lists_only_bridged_members(client):
    await _make_room(client)
    _register_a2a()
    _register_resident()

    state = (await client.get(_STATE)).json()

    assert [a["handle"] for a in state["agents"]] == ["researcher"]
    agent = state["agents"][0]
    assert agent["endpoint"] == "https://remote.example/a2a"
    assert agent["skills"] == ["research", "summarize"]
    # The honest cue: proxied by the hub, never an MLS group member.
    assert agent["proxied"] is True


@pytest.mark.asyncio
async def test_exposure_points_at_the_served_card(client):
    await _make_room(client)
    write_memory_file(
        get_room_dir(_ROOM),
        "skills/summarize",
        "Distill the room.",
        created_by="web-ui",
        extra_meta={"description": "distills the room"},
    )

    exposure = (await client.get(_STATE)).json()["exposure"]

    assert exposure["card_url"].endswith(f"/api/rooms/{_ROOM}/.well-known/agent-card.json")
    assert exposure["rpc_url"].endswith(f"/api/rooms/{_ROOM}/a2a")
    assert exposure["skills"] == ["summarize"]
    # Nothing has read the card yet.
    assert exposure["card_fetches"] == 0

    await client.get(f"/api/rooms/{_ROOM}/.well-known/agent-card.json")
    exposure = (await client.get(_STATE)).json()["exposure"]
    assert exposure["card_fetches"] == 1
    assert exposure["last_card_fetch_at"]


@pytest.mark.asyncio
async def test_outbound_call_shows_up_as_an_exchange(client):
    await _make_room(client)
    _register_a2a()
    a2a_activity.record_outbound(
        _ROOM,
        "researcher",
        status="ok",
        endpoint="https://remote.example/a2a",
        peer="avery",
        prompt="what do you think?",
        reply="I think so",
        duration_ms=42,
    )

    state = (await client.get(_STATE)).json()

    assert state["outbound_ok"] == 1
    assert state["outbound_failed"] == 0
    exchange = state["exchanges"][-1]
    assert exchange["direction"] == "outbound"
    assert exchange["status"] == "ok"
    assert exchange["handle"] == "researcher"
    assert exchange["peer"] == "avery"
    assert exchange["reply"] == "I think so"
    assert exchange["duration_ms"] == 42
    # The per-agent counters roll up the same call.
    assert state["agents"][0]["calls_ok"] == 1
    assert state["agents"][0]["last_call_at"]


@pytest.mark.asyncio
async def test_failed_call_is_recorded_with_its_reason(client):
    await _make_room(client)
    _register_a2a()
    a2a_activity.record_outbound(
        _ROOM, "researcher", status="error", detail="card unresolvable: 404"
    )

    state = (await client.get(_STATE)).json()

    assert state["outbound_failed"] == 1
    assert state["agents"][0]["calls_failed"] == 1
    assert state["exchanges"][-1]["detail"] == "card unresolvable: 404"


@pytest.mark.asyncio
async def test_activity_is_room_scoped(client):
    await _make_room(client)
    await _make_room(client, "other")
    a2a_activity.record_outbound("other", "researcher", status="ok")

    state = (await client.get(_STATE)).json()

    assert state["exchanges"] == []
    assert state["outbound_ok"] == 0


@pytest.mark.asyncio
async def test_quiet_room_reports_an_empty_bridge(client):
    await _make_room(client)

    state = (await client.get(_STATE)).json()

    assert state["room"] == _ROOM
    assert state["agents"] == []
    assert state["exchanges"] == []


@pytest.mark.asyncio
async def test_unknown_room_is_404(client):
    assert (await client.get("/api/rooms/ghost/a2a/state")).status_code == 404


def test_previews_are_bounded():
    long_prompt = "word " * 500
    exchange = a2a_activity.record_outbound(_ROOM, "researcher", status="ok", prompt=long_prompt)
    assert len(exchange.prompt) <= a2a_activity.PREVIEW_CHARS


def test_ring_keeps_the_recent_tail():
    for i in range(a2a_activity.RING + 10):
        a2a_activity.record_outbound(_ROOM, "researcher", status="ok", prompt=f"call {i}")

    kept = a2a_activity.recent(_ROOM)

    assert len(kept) == a2a_activity.RING
    assert kept[-1].prompt == f"call {a2a_activity.RING + 9}"
    # Counters are lifetime, not window-bounded.
    assert a2a_activity.totals(_ROOM).outbound_ok == a2a_activity.RING + 10
