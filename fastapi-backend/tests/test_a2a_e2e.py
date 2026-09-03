# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""End-to-end A2A bridge smoke test (#718) against a LIVE public agent.

Env-gated (``MYCELIUM_A2A_LIVE=1``) so CI stays hermetic. Unlike the unit tests,
nothing here is mocked on the A2A side: it registers a real remote agent through
the real backend route (which resolves its live Agent Card), then drives a real
``@``-mention through the responder so the live remote is actually called and its
reply is posted back. The room channel is faked (no SLIM node needed); the A2A
hop is real.

The public echo agent returns "Hello World" for any input — enough to prove the
whole outbound chat path end to end. Point it at a model-backed a2a-samples agent
for a behavioral run.
"""

import asyncio
import os

import pytest

from app.services import a2a_bridge, l9, room_channels
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakePersister

pytestmark = pytest.mark.skipif(
    os.getenv("MYCELIUM_A2A_LIVE") != "1",
    reason="live A2A e2e; set MYCELIUM_A2A_LIVE=1 to run",
)

_ECHO = "https://hello-world-gxfr.onrender.com"
_ROOM = "portfolio"


@pytest.mark.asyncio
async def test_register_then_chat_with_a_live_a2a_agent(client, monkeypatch):
    # 1. Register the live agent through the real route — resolves its live card.
    assert (await client.post("/api/rooms", json={"name": _ROOM})).status_code in (200, 201)
    resp = await client.post(
        f"/api/rooms/{_ROOM}/a2a-agents", json={"handle": "echo", "card": _ECHO}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["adapter"] == "a2a"
    assert body["a2a_endpoint"]  # a real endpoint came back from the live card

    # 2. @-mention it. The responder calls the LIVE agent and posts its reply.
    persister = FakePersister()
    channel = FakeChannel(persister)
    managed = FakeManaged(room=_ROOM, channel=channel, persister=persister)
    monkeypatch.setattr(room_channels.manager, "get", lambda _r: managed)

    responder = a2a_bridge.A2aResponder(room_channels.manager)
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=l9.episode_urn(_ROOM, "live"),
        sender="avery",
        sender_role="human",
        recipients=["echo"],
        topic=l9.topic_urn(_ROOM),
        payload_type="message",
        message_id="m1",
    )
    responder.handle_summon(_ROOM, "echo", env, [], "hello there")
    await asyncio.gather(*list(responder._tasks))

    posted = [extra.get("content") for _env, extra in channel.sent if extra]
    assert any("Hello World" in (p or "") for p in posted), posted
