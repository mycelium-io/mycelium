# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""PoC (#726): carry the A2A bridge's outbound hop over SLIM instead of HTTPS.

The outbound send today (:func:`app.services.a2a_bridge.send_to_a2a`) talks A2A
over plain HTTPS. AGNTCY's ``slima2a`` (agntcy/slim-a2a-python) is a SLIMRPC
transport for the a2a-python SDK, so the same A2A ``send_message`` can ride SLIM
with SLIM-identity auth and SLIM's encryption. :func:`send_over_slim` is that
path, structurally identical to the HTTP send (build client -> send -> collect
parts) but over a SLIM channel.

**PoC scope / honesty.** This is a proof of concept for the HTTP-vs-SLIM decision,
NOT merged behavior. Two facts to weigh (see #726):

- ``slima2a`` pins ``a2a-sdk==1.1.0`` exactly; adopting it pins the whole bridge
  to 1.1.0 (the full backend suite passes there — that's the main cost).
- SLIMRPC is point-to-point RPC to a distinct SLIM identity, so this hardens the
  hop; it does **not** make the remote a member of the room's MLS group.

Reaching a remote over SLIM needs the remote to run a ``slima2a`` server
(``SRPCHandler``) with a SLIM name, and a reachable SLIM node — so the live
round-trip is env-gated, not a unit test.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest, StreamResponse
from slima2a import setup_slim_client
from slima2a.client_transport import (
    ClientConfig,
    MultiAgentClientFactory,
    slimrpc_channel_factory,
)

from app.config import settings
from app.services.a2a_bridge import A2aReply, A2aSendError, _collect
from app.services.slim_client import resolve_master_secret

logger = logging.getLogger(__name__)

# Our SLIM client identity when calling out as the bridge. A namespace/group/name
# triple, the SLIM addressing unit. The PoC uses one fixed caller identity.
_CALLER_NS = "mycelium"
_CALLER_GROUP = "a2a-bridge"
_CALLER_NAME = "outbound-seat"

# slima2a's setup_slim_client retries a connection rather than failing fast, so
# an unreachable node would hang. Bound it (a real operational consideration for
# the HTTP-vs-SLIM decision — HTTP surfaces a connect error immediately).
_CONNECT_TIMEOUT_S = 10.0


async def send_over_slim(
    card: AgentCard,
    text: str,
    *,
    context_id: str | None = None,
    slim_url: str | None = None,
    secret: str | None = None,
) -> A2aReply:
    """Send ``text`` to a SLIM-reachable A2A agent (described by ``card``).

    ``card`` is the remote's Agent Card carrying a SLIM interface (its SLIM
    name). Mirrors :func:`send_to_a2a` but over SLIMRPC. Raises
    :class:`A2aSendError` on failure so the caller falls back faithfully.
    """
    url = slim_url or settings.SLIM_NODE_ENDPOINT
    key = secret or resolve_master_secret()
    try:
        _service, app_handle, _local_name, conn_id = await asyncio.wait_for(
            setup_slim_client(_CALLER_NS, _CALLER_GROUP, _CALLER_NAME, slim_url=url, secret=key),
            timeout=_CONNECT_TIMEOUT_S,
        )
    except Exception as exc:  # timeout or any SLIM setup failure -> send failure
        raise A2aSendError(f"SLIM connect failed ({url}): {exc}") from exc

    channel_factory = slimrpc_channel_factory(app_handle, conn_id)
    streaming = bool(getattr(getattr(card, "capabilities", None), "streaming", False))
    config = ClientConfig(
        streaming=streaming,
        accepted_output_modes=["text"],
        grpc_channel_factory=channel_factory,
    )
    client = MultiAgentClientFactory(config).create(card=card)

    message = Message(message_id="mycelium-seat", role=Role.ROLE_USER, parts=[Part(text=text)])
    if context_id:
        message.context_id = context_id

    chunks: list[str] = []
    thread: str | None = context_id
    try:
        async for response in client.send_message(SendMessageRequest(message=message)):
            chunk, ctx = _collect(cast(StreamResponse, response))
            if chunk:
                chunks.append(chunk)
            if ctx:
                thread = ctx
    except Exception as exc:  # SLIMRPC surfaces various transport errors
        raise A2aSendError(f"SLIM send failed: {exc}") from exc

    reply = " ".join(c for c in chunks if c).strip()
    if not reply:
        raise A2aSendError("remote agent returned no text over SLIM")
    return A2aReply(text=reply, context_id=thread)
