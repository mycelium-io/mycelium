# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Expose a room as an A2A agent (#716) — the inbound mirror.

The card is resolved by the *real* a2a-sdk client over the app's ASGI transport
(proving wire compatibility). The message/send path is driven with a raw
JSON-RPC POST — the server's dispatcher parses it and runs our executor — so the
test exercises our server without depending on the SDK client's streaming
iterator semantics over ASGITransport.
"""

import pytest
from a2a.client import A2ACardResolver

from app.services import room_channels
from app.services.filesystem import get_room_dir, write_memory_file
from tests.fakes import FakeChannel, FakeManaged, FakePersister

_CARD_PATH = "/api/rooms/portfolio/.well-known/agent-card.json"


async def _make_room(client, name: str = "portfolio") -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201)


async def _resolve(client):
    return await A2ACardResolver(client, "http://test", agent_card_path=_CARD_PATH).get_agent_card()


@pytest.mark.asyncio
async def test_room_card_is_resolvable_by_the_sdk(client):
    await _make_room(client)
    # Seed a skill directly (no embedding) so the card projects it.
    write_memory_file(
        get_room_dir("portfolio"),
        "skills/summarize",
        "Distill the room.",
        created_by="web-ui",
        extra_meta={"description": "distills the room"},
    )

    card = await _resolve(client)
    assert card.name == "portfolio"
    skill = next((s for s in card.skills if s.id == "summarize"), None)
    assert skill is not None
    assert skill.description == "distills the room"
    # the SDK derived a JSON-RPC endpoint from the card
    assert any(i.url.endswith("/api/rooms/portfolio/a2a") for i in card.supported_interfaces)


@pytest.mark.asyncio
async def test_missing_room_card_is_404(client):
    resolver = A2ACardResolver(
        client, "http://test", agent_card_path="/api/rooms/ghost/.well-known/agent-card.json"
    )
    with pytest.raises(Exception):  # noqa: B017 - resolver raises on non-200
        await resolver.get_agent_card()


@pytest.mark.asyncio
async def test_message_send_delivers_into_the_room(client, monkeypatch):
    await _make_room(client)

    # Route the room injection at a fake channel so we can assert delivery.
    persister = FakePersister()
    channel = FakeChannel(persister)
    managed = FakeManaged(room="portfolio", channel=channel, persister=persister)
    monkeypatch.setattr(room_channels.manager, "get", lambda _r: managed)

    rpc = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "configuration": {"acceptedOutputModes": ["text"]},
            "message": {
                "kind": "message",
                "messageId": "in1",
                "role": "user",
                "parts": [{"kind": "text", "text": "hello room"}],
            },
        },
    }
    resp = await client.post("/api/rooms/portfolio/a2a", json=rpc)
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    ack = "".join(p.get("text", "") for p in result["parts"])
    assert "Delivered to room" in ack
    # the message actually reached the room channel
    assert any(extra and extra.get("content") == "hello room" for _env, extra in channel.sent)
    # …and the Network views can see the inbound turn (#739)
    state = (await client.get("/api/rooms/portfolio/a2a/state")).json()
    assert state["exposure"]["messages"] == 1
    assert state["exchanges"][-1]["direction"] == "inbound"
    assert state["exchanges"][-1]["prompt"] == "hello room"


@pytest.mark.asyncio
async def test_message_send_missing_room_404(client):
    rpc = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {"message": {"kind": "message", "messageId": "x", "role": "user", "parts": []}},
    }
    resp = await client.post("/api/rooms/ghost/a2a", json=rpc)
    assert resp.status_code == 404


def _send_rpc(text: str = "ping") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "configuration": {"acceptedOutputModes": ["text"]},
            "message": {
                "kind": "message",
                "messageId": "in-auth",
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
            },
        },
    }


def _wire_room(monkeypatch, room: str = "portfolio") -> FakeChannel:
    """Point the room's channel at a fake so the sender is assertable."""
    persister = FakePersister()
    channel = FakeChannel(persister)
    monkeypatch.setattr(
        room_channels.manager,
        "get",
        lambda _r: FakeManaged(room=room, channel=channel, persister=persister),
    )
    return channel


@pytest.mark.asyncio
async def test_authenticated_caller_posts_under_its_own_handle(client, monkeypatch, as_principal):
    """A gated hub already proved the caller; the room says who it was (#798)."""
    await _make_room(client)
    channel = _wire_room(monkeypatch)
    as_principal("claude-web")

    resp = await client.post("/api/rooms/portfolio/a2a", json=_send_rpc())
    assert resp.status_code == 200, resp.text

    env, _extra = channel.sent[-1]
    assert [a.id for a in env.header.participants.actors] == ["claude-web"]
    # …and the Network views name the caller too, not a shared guest.
    state = (await client.get("/api/rooms/portfolio/a2a/state")).json()
    assert state["exchanges"][-1]["handle"] == "claude-web"


@pytest.mark.asyncio
async def test_anonymous_caller_falls_back_to_the_guest_handle(client, monkeypatch, as_principal):
    """An ungated hub has no verified identity to name, so nothing changes."""
    await _make_room(client)
    channel = _wire_room(monkeypatch)
    as_principal(None)

    resp = await client.post("/api/rooms/portfolio/a2a", json=_send_rpc())
    assert resp.status_code == 200, resp.text

    env, _extra = channel.sent[-1]
    assert [a.id for a in env.header.participants.actors] == ["a2a-guest"]
    state = (await client.get("/api/rooms/portfolio/a2a/state")).json()
    assert state["exchanges"][-1]["handle"] == "a2a-guest"


@pytest.mark.asyncio
async def test_two_callers_are_distinguishable_in_the_room(client, monkeypatch, as_principal):
    """The point of the change: the room can tell external agents apart."""
    await _make_room(client)
    channel = _wire_room(monkeypatch)

    for handle in ("claude-web", "atlas-agent"):
        as_principal(handle)
        resp = await client.post("/api/rooms/portfolio/a2a", json=_send_rpc(f"from {handle}"))
        assert resp.status_code == 200, resp.text

    senders = [env.header.participants.actors[0].id for env, _extra in channel.sent]
    assert senders == ["claude-web", "atlas-agent"]
