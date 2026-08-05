# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Connector wake — live-node integration slice (Step 5 DoD).

Needs a running ``slim`` node. Guarded so the default unit suite stays green
without one (mirrors the backend's ``test_l9_over_slim_roundtrip.py``): point at
a node with ``MYCELIUM_SLIM_ENDPOINT`` (default ``http://127.0.0.1:46357``); run
one via ``mycelium hub host`` or the docker recipe in ``START_HERE_STEP_5.md``.

Proves the Step 5 DoD end-to-end over a real MLS group channel: a mock
"backend" moderator invites the connector's handle, publishes an L9 ``exchange``
addressed to it, and the connector — spawning a **mocked** ``claude`` at the
integration boundary — wakes and publishes its reply, which the moderator
receives as a valid ``exchange`` authored by the handle and parented on the
message that woke it.

The connector's transport primitives (``SlimClient`` member session +
``handle_inbound``) are driven directly here rather than through the full
``run_connector`` reconnect loop; that loop is thin glue over these same
primitives and is unit-covered in ``test_daemon_connector.py``.
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
_ROOM = "connector-wake-room"
_HANDLE = "agent-a"
_WOKE_ID = "woke-1"


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
async def test_connector_wakes_and_replies_over_slim(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock the cold spawn — no real `claude` binary in CI.
    spawn = AsyncMock(
        return_value=SpawnResult(
            ok=True, final_message="woke and replied", transcript="", cost_usd=0.0, duration_s=0.0
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

        # Pull the moderator's inbound and run the real connector dispatch.
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
        # Address an exchange at the connector's handle; it should wake + reply.
        inbound = l9.build_reply_content(
            sender="backend",
            recipients=[_HANDLE],
            episode="urn:ioc:mycelium:episode:connector-wake-room:live",
            parents=[],
            topic="urn:concept:mycelium:connector-wake-room",
            text=f"@{_HANDLE} please take a turn",
            message_id=_WOKE_ID,
            payload_type="tick",
        )
        await SlimClient.publish(session, l9.serialize(inbound))

        while not received:
            msg = await SlimClient.receive_message(session, timeout_s=15.0)
            parsed = l9.parse(msg.payload)
            # Take the connector's reply (authored by the handle); ignore the
            # moderator's own echo of the inbound.
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
    assert reply["l9"]["header"]["message"]["parents"] == [_WOKE_ID]
    assert l9.human_text_of(reply) == "woke and replied"
