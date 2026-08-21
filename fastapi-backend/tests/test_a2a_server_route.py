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
