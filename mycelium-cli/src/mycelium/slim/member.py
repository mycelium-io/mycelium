# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Ephemeral SLIM room membership: join, publish once, leave (dev/testing).

The CLI's ``l9 send`` / ``slim send`` plumbing (see ``mycelium.commands.wire``)
needs to put real bytes on a room's SLIM channel so the backend's own
already-running persister sees them, records them to the durable transcript, and
republishes to its in-process bus (which feeds SSE). A separate process writing
straight to that bus can't reach it: ``bus`` is per-process, so a ``docker exec
python`` script publishing to its own copy of it never reaches the running
server's subscribers. Riding the real channel is the only way in from outside
the backend's process.

The backend is every room's sole moderator (``app/services/room_channels.py``);
it never gets invited, it invites. So a short-lived CLI process has to ask the
backend to invite it before it can publish, the same join call a resident
connector makes on every reconnect (``POST /rooms/{room}/sessions``,
``app/routes/sessions.py::join_room`` → ``room_channels.manager.invite_in_background``).
That call is fire-and-forget on the backend side, with its own retrying
handshake, so asking before this process has even connected to the node is fine.
"""

from __future__ import annotations

import asyncio

import httpx

from mycelium.slim.client import SlimClient, SlimError
from mycelium.slim.naming import DEFAULT_WORKSPACE, SlimIdentity, node_reachable

# How long to wait, after asking the backend to invite us, for the moderator's
# handshake to land and admit us into the encrypted group. Comfortably inside the
# backend's own invite retry budget (5 retries * 5s interval = 25s, see
# ``SlimClient._group_session_config``).
DEFAULT_JOIN_TIMEOUT_S = 30.0

# The join request is a same-host call to the backend, not the SLIM handshake
# itself, so it gets a short budget.
_HTTP_TIMEOUT_S = 10.0


class SlimSendError(SlimError):
    """A join/connect/publish attempt as an ephemeral room member failed."""


async def announce_presence(api_url: str, room: str, handle: str) -> None:
    """Ask the backend to (re)invite ``handle`` into ``room``'s SLIM group.

    Mirrors ``ParticipantCreate``, the same request body a resident connector
    sends on every join/reconnect.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
        resp = await client.post(
            f"{api_url}/api/rooms/{room}/sessions", json={"agent_handle": handle}
        )
    resp.raise_for_status()


async def publish_once(
    *,
    api_url: str,
    node_endpoint: str,
    room: str,
    handle: str,
    payload: bytes,
    workspace: str = DEFAULT_WORKSPACE,
    join_timeout_s: float = DEFAULT_JOIN_TIMEOUT_S,
) -> None:
    """Join ``room`` as ``handle`` over a live SLIM connection, publish once, leave.

    Connects a new SLIM app under ``workspace/room/handle``, asks the backend to
    invite it in, waits to be admitted into the moderator's encrypted group,
    publishes ``payload`` verbatim, and disconnects. Raises :class:`SlimSendError`
    if the node is unreachable or the invite never lands within
    ``join_timeout_s``; raises :class:`~mycelium.slim.client.SlimUnavailableError`
    (via ``SlimClient.connect``) if ``slim_bindings`` has no wheel for this
    platform; both are :class:`~mycelium.slim.client.SlimError`.
    """
    if not node_reachable(node_endpoint):
        raise SlimSendError(
            f"SLIM node unreachable at {node_endpoint}; is `mycelium hub host` "
            "(or the node's compose service) running?"
        )

    identity = SlimIdentity(workspace, room, handle)
    client = await SlimClient(identity).connect(node_endpoint)
    try:
        await announce_presence(api_url, room, handle)
        try:
            session = await asyncio.wait_for(client.listen_for_session(), timeout=join_timeout_s)
        except TimeoutError as exc:
            raise SlimSendError(
                f"timed out waiting to be invited into room {room!r} as @{handle} "
                "(is the backend up and moderating this room?)"
            ) from exc
        await SlimClient.publish(session, payload)
    finally:
        await client.close()
