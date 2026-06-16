# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Session sub-room SSE subscriber.

Negotiation session messages (``coordination_tick``,
``coordination_consensus``) are posted into a sub-room named
``<parent>:session:<id>`` rather than the parent room. We have to open a
separate SSE subscription to that sub-room when a ``coordination_join``
or ``coordination_start`` lands in the parent stream — see
:func:`route_message` returning a :class:`SubscribeSession` action.

This is a thin specialization of :mod:`room_sse`: the SSE wire format is
identical and the only difference is the URL path. Concentrating the
SSE plumbing in one helper keeps both stream consumers in sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .room_sse import subscribe_room

if TYPE_CHECKING:
    import aiohttp

    from .room_sse import MessageHandler


async def subscribe_session(
    *,
    session: aiohttp.ClientSession,
    backend_url: str,
    session_room: str,
    on_message: MessageHandler,
    api_token: str | None = None,
) -> None:
    """Open a reconnecting SSE subscription to a session sub-room."""
    await subscribe_room(
        session=session,
        backend_url=backend_url,
        room=session_room,
        on_message=on_message,
        api_token=api_token,
    )
