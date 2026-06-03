# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Asyncio SSE subscriber for a Mycelium room's message stream.

Mirror of the openclaw plugin's ``room-sse.ts``: long-lived asyncio task
that holds an HTTP connection to ``<backend>/api/rooms/{room}/messages/
stream``, parses each Server-Sent Event into a Python dict, and hands it
to a callback for routing.

Reconnect policy: on disconnect, sleep with exponential backoff (1s → 2s
→ 4s → 8s, capped at 30s) and try again. ``asyncio.CancelledError`` is
re-raised so the adapter's :meth:`disconnect` can cleanly tear it down.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]

_BACKOFF_INITIAL_S = 1.0
_BACKOFF_MAX_S = 30.0
_READ_TIMEOUT_S = 120.0  # long-poll friendly; SSE keepalives are infrequent


async def subscribe_room(
    *,
    session: aiohttp.ClientSession,
    backend_url: str,
    room: str,
    on_message: MessageHandler,
    api_token: str | None = None,
) -> None:
    """Open a reconnecting SSE subscription to *room* and forward events.

    Runs until cancelled. Errors during a single connection trigger
    backoff and reconnect; the connection itself is held open as long as
    the server keeps the stream alive (or until a CancelledError fires).
    """
    url = f"{backend_url.rstrip('/')}/api/rooms/{room}/messages/stream"
    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    backoff = _BACKOFF_INITIAL_S
    while True:
        try:
            await _stream_once(
                session=session,
                url=url,
                headers=headers,
                room=room,
                on_message=on_message,
            )
            # Server closed cleanly — reset backoff and reconnect immediately.
            backoff = _BACKOFF_INITIAL_S
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            logger.warning(
                "mycelium-room: SSE %s closed (%s) — reconnecting in %.1fs",
                room,
                exc,
                backoff,
            )
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            backoff = min(_BACKOFF_MAX_S, backoff * 2)


async def _stream_once(
    *,
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    room: str,
    on_message: MessageHandler,
) -> None:
    """One connection's worth of streaming. Returns on clean EOF; raises
    on transport errors so the outer loop can back off and reconnect."""
    timeout = aiohttp.ClientTimeout(total=None, sock_read=_READ_TIMEOUT_S)
    async with session.get(url, headers=headers, timeout=timeout) as resp:
        if resp.status >= 400:
            body = (await resp.text())[:240]
            raise aiohttp.ClientResponseError(
                resp.request_info,
                resp.history,
                status=resp.status,
                message=f"SSE {room} → HTTP {resp.status}: {body}",
                headers=resp.headers,
            )
        logger.info("mycelium-room: SSE connected to %s", room)
        async for raw in _iter_events(resp):
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("mycelium-room: dropping non-JSON SSE frame: %r", raw[:120])
                continue
            if not isinstance(payload, dict):
                continue
            try:
                await on_message(payload)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — never let one event kill the stream
                logger.exception(
                    "mycelium-room: handler error on room=%s id=%s",
                    room,
                    payload.get("id"),
                )


async def _iter_events(resp: aiohttp.ClientResponse):  # noqa: ANN201
    """Yield ``data:`` payloads from a Server-Sent Events stream.

    SSE frames are separated by blank lines and each frame is a list of
    ``field: value`` lines. We only need the ``data:`` field; everything
    else (``event:``, ``id:``, ``retry:``, ``: comment``) is ignored. A
    multi-line ``data`` is joined with ``\\n`` per the SSE spec.
    """
    data_lines: list[str] = []
    async for raw in resp.content:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue  # heartbeat / comment
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
