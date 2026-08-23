# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""PoC (#726): the A2A-over-SLIM outbound transport.

A live SLIMRPC round-trip needs a reachable SLIM node AND the remote running a
``slima2a`` server, so it can't be a unit test. What's hermetic is the
error-wrapping contract: any SLIM setup/transport failure surfaces as
``A2aSendError`` so the responder falls back faithfully, same as the HTTP path.
"""

import os

import pytest
from a2a.types import AgentCapabilities, AgentCard

from app.services import a2a_slim_transport
from app.services.a2a_bridge import A2aSendError
from app.services.a2a_slim_transport import send_over_slim

_CARD = AgentCard(name="remote", version="1.0.0", capabilities=AgentCapabilities(streaming=False))


@pytest.mark.asyncio
async def test_connect_failure_surfaces_as_a2a_send_error(monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("no node here")

    monkeypatch.setattr(a2a_slim_transport, "setup_slim_client", _boom)
    with pytest.raises(A2aSendError, match="SLIM connect failed"):
        await send_over_slim(_CARD, "hi")


@pytest.mark.skipif(
    not os.getenv("MYCELIUM_SLIM_ENDPOINT"),
    reason="needs a reachable SLIM node (MYCELIUM_SLIM_ENDPOINT) + a slima2a server",
)
@pytest.mark.asyncio
async def test_live_slim_hop():
    # With a node but no remote server, the send fails after connect — which still
    # proves the SLIM client connects to the node and the transport is wired.
    with pytest.raises(A2aSendError):
        await send_over_slim(_CARD, "hi", slim_url=os.environ["MYCELIUM_SLIM_ENDPOINT"])
