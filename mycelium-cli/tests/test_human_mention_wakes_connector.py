# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Human ``@``-mention wakes the connector — live-node integration slice.

The backend, as the human's spoken-for proxy, publishes the human's message onto
the channel with the mentioned agent as an L9 recipient. This slice proves that a
message authored by a *human* handle (not another agent's connector) wakes the
connector and its reply lands back in the room.

Needs a running ``slim`` node (guarded, like ``test_connector_wake_over_slim.py``):
point at one with ``MYCELIUM_SLIM_ENDPOINT`` (default ``http://127.0.0.1:46357``);
run via ``mycelium hub host``. The consent (not-in-room invite) half is backend-side
and unit-covered in ``fastapi-backend/tests/test_mentions_and_invites.py``.
"""

from __future__ import annotations

import asyncio
import os
import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlparse

import pytest

pytest.importorskip("slim_bindings")

from mycelium.config import MyceliumConfig, ServerConfig
from mycelium.daemon import connector
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.state import DaemonState
from mycelium.integrations._spawn_common import SpawnResult
from mycelium.protocol import AgentManifest
from mycelium.slim import l9
from mycelium.slim.client import SlimClient, close_connection
from mycelium.slim.naming import DEFAULT_NODE_ENDPOINT, SlimIdentity, to_channel_name, to_slim_name

_ENDPOINT = os.getenv("MYCELIUM_SLIM_ENDPOINT", DEFAULT_NODE_ENDPOINT)
_WORKSPACE = "mycelium"
_ROOM = "human-mention-room"
_HANDLE = "agent-a"
_HUMAN = "julia"
_WOKE_ID = "human-woke-1"


def _node_reachable(endpoint: str, *, timeout: float = 1.0) -> bool:
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 46357
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _node_reachable(_ENDPOINT),
    reason=f"no reachable SLIM node at {_ENDPOINT} (set MYCELIUM_SLIM_ENDPOINT or run `mycelium hub host`)",
)


@pytest.mark.asyncio
async def test_human_mention_wakes_connector_over_slim(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock the cold spawn — no real `claude` binary in CI.
    spawn = AsyncMock(
        return_value=SpawnResult(
            ok=True, final_message="on it", transcript="", cost_usd=0.0, duration_s=0.0
        )
    )
    integration = MagicMock(lifecycle="cold_spawn", spawn=spawn)
    monkeypatch.setattr(connector, "get_integration", lambda _adapter: integration)
    monkeypatch.setattr(connector, "_fetch_agent_context", AsyncMock(return_value=(None, "")))
    monkeypatch.setattr(connector, "_post_log", AsyncMock(return_value=None))
    monkeypatch.setattr(connector, "load_notes", lambda _room, _handle: "")
    monkeypatch.setattr(
        connector,
        "load_manifest",
        lambda _room, _handle: AgentManifest(
            handle=_HANDLE, adapter="claude_code", cwd="/tmp/x", description="participant"
        ),
    )

    moderator = await SlimClient(SlimIdentity(_WORKSPACE, _ROOM, "backend")).connect(_ENDPOINT)
    member = await SlimClient(SlimIdentity(_WORKSPACE, _ROOM, _HANDLE)).connect(_ENDPOINT)

    session = await moderator.create_group(to_channel_name(_WORKSPACE, _ROOM))

    async def member_side() -> None:
        joined = await member.listen_for_session()

        async def publish(content: dict) -> None:
            await SlimClient.publish(joined, l9.serialize(content))

        message = await SlimClient.receive_message(joined, timeout_s=15.0)
        content = l9.parse(message.payload)
        assert content is not None
        await connector.handle_inbound(
            config=MyceliumConfig(server=ServerConfig(api_url="http://localhost:8000")),
            daemon_cfg=DaemonConfig(),
            state=DaemonState(),
            room=_ROOM,
            handle=_HANDLE,
            content=content,
            publish=publish,
        )

    member_task = asyncio.create_task(member_side())
    received: list[dict[str, Any]] = []
    try:
        await moderator.invite(session, to_slim_name(_WORKSPACE, _ROOM, _HANDLE))
        # The backend publishes the HUMAN's message onto the channel (spoken-for
        # proxy): sender is a human handle, the mentioned agent is an L9 recipient.
        inbound = l9.build_reply_content(
            sender=_HUMAN,
            recipients=[_HANDLE],
            episode="urn:ioc:mycelium:episode:human-mention-room:live",
            parents=[],
            topic="urn:concept:mycelium:human-mention-room",
            text=f"@{_HANDLE} can you take this?",
            message_id=_WOKE_ID,
            payload_type="message",
        )
        await SlimClient.publish(session, l9.serialize(inbound))

        while not received:
            msg = await SlimClient.receive_message(session, timeout_s=15.0)
            parsed = l9.parse(msg.payload)
            if parsed is not None and l9.sender_of(parsed) == _HANDLE:
                received.append(parsed)
    finally:
        member_task.cancel()
        try:
            await member_task
        except asyncio.CancelledError:
            pass
        await moderator.close()
        await member.close()
        await close_connection(_ENDPOINT)

    spawn.assert_awaited_once()
    reply = received[0]
    assert l9.kind_of(reply) == "exchange"
    assert l9.sender_of(reply) == _HANDLE
    # Reply is parented on the human's message and addressed back to the human.
    assert reply["l9"]["header"]["message"]["parents"] == [_WOKE_ID]
    assert l9.recipients_of(reply) == [_HUMAN]
    assert l9.human_text_of(reply) == "on it"
