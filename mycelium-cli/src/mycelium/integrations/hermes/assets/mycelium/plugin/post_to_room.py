# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST a message to a Mycelium room.

The mirror of the openclaw plugin's ``post-to-room.ts``. We POST to
``<backend_url>/api/rooms/{room}/messages`` with the agent's reply text;
the backend appends it to the room and broadcasts to SSE subscribers
(including us, which is why the adapter caches the returned message id
in its ``_own_message_ids`` set for loop suppression).

aiohttp is the only HTTP client we use — it's already in the hermes
dependency closure (webhook adapter uses it), so the plugin doesn't add
anything new.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


async def _do_post(
    *,
    session: aiohttp.ClientSession,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> str | None:
    async with session.post(url, json=payload, headers=headers) as resp:
        if resp.status >= 400:
            body = (await resp.text())[:240]
            logger.warning("mycelium room POST failed: %s %s — %s", resp.status, url, body)
            return None
        data = await resp.json(content_type=None)
        if isinstance(data, dict):
            mid = data.get("id")
            if isinstance(mid, str):
                return mid
    return None


async def post_to_room(
    *,
    session: aiohttp.ClientSession,
    backend_url: str,
    room: str,
    sender_handle: str,
    content: str,
    api_token: str | None = None,
    timeout: float = 15.0,
) -> str | None:
    """POST ``content`` to *room*; return the backend-assigned message id.

    Best-effort: a transport error logs and returns ``None`` so the agent
    loop can decide whether to retry or surface the failure — we never
    raise out of the platform send path.

    Timeouts via ``asyncio.wait_for`` rather than ``aiohttp.ClientTimeout``.
    aiohttp's per-call ``timeout`` arg uses ``asyncio.timeout()`` under the
    hood, which RuntimeErrors with "Timeout context manager should be used
    inside a task" when the call enters from a code path that hasn't
    established a task scope — and the hermes tool_executor invokes us via
    exactly that kind of edge (the ``send_message`` tool runs the adapter
    send under a thread executor → loop bridge). ``asyncio.wait_for`` is
    task-agnostic and works under both paths, so use it consistently
    rather than depending on aiohttp's internals.
    """
    url = f"{backend_url.rstrip('/')}/api/rooms/{room}/messages"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_token:
        # The mycelium backend treats Bearer tokens as authenticated identity;
        # the plugin lifts the token from platforms.mycelium-room.extra.api_token.
        headers["Authorization"] = f"Bearer {api_token}"
    # ``message_type`` is required by the backend's ``MessageCreate`` schema
    # (``announce|direct|broadcast|delegate``). Agents posting back into a
    # room speak to everyone subscribed, so ``broadcast`` matches what the
    # openclaw TS plugin does (``post-to-room.ts:34``).
    payload: dict[str, Any] = {
        "sender_handle": sender_handle,
        "content": content,
        "message_type": "broadcast",
    }
    try:
        return await asyncio.wait_for(
            _do_post(session=session, url=url, payload=payload, headers=headers),
            timeout=timeout,
        )
    except (aiohttp.ClientError, TimeoutError) as exc:
        # asyncio.TimeoutError is aliased to the builtin TimeoutError on
        # Python 3.11+, so the single ``TimeoutError`` catches both the
        # ``asyncio.wait_for`` timeout and any underlying transport
        # timeout — ruff (UP041) confirms the alias collapse.
        logger.warning("mycelium room POST transport error: %s — %s", url, exc)
    return None
