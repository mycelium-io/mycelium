# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Drive a registered A2A agent as a backend-held room seat (epic #719, #714).

The bridge's client leg. :func:`send_to_a2a` is the one primitive that matters:
given a remote agent's card URL and a prompt, call it over A2A and return its
reply text. Everything the seat loop does around it (hold membership, watch for
ticks addressed to the handle, post the reply as that handle) is the same
``await``/``respond`` turn a resident agent runs, so the aligner addresses the
seat exactly like any other member.

The send path carries the #712 spike findings: resolve the card (dual well-known
path), then build a client with ``accepted_output_modes`` set — without it,
older servers reject the send with a pydantic ``-32600``.
"""

from __future__ import annotations

import logging

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.types import Message, Part, Role, SendMessageRequest

from app.services.a2a_card import A2aCardError, resolve_raw_card

logger = logging.getLogger(__name__)

_SEND_TIMEOUT_S = 120.0


class A2aSendError(Exception):
    """A round-trip to the remote A2A agent failed."""


def _reply_text(response: object) -> str:
    """Pull the text parts out of one A2A stream response, if any."""
    message = getattr(response, "message", None)
    if message is None or not getattr(response, "HasField", lambda _f: False)("message"):
        return ""
    parts = getattr(message, "parts", []) or []
    return "".join(p.text for p in parts if p.HasField("text"))


async def send_to_a2a(
    card_url: str,
    text: str,
    *,
    http: httpx.AsyncClient | None = None,
    timeout_s: float = _SEND_TIMEOUT_S,
) -> str:
    """Send ``text`` to the A2A agent at ``card_url`` and return its reply prose.

    Raises :class:`A2aSendError` on an unresolvable card or a failed exchange, so
    the seat can fall back faithfully (silence, never a fabricated reply).
    """
    owns_client = http is None
    client_http = http or httpx.AsyncClient(timeout=timeout_s)
    try:
        try:
            card, _path = await resolve_raw_card(card_url, http=client_http)
        except A2aCardError as exc:
            raise A2aSendError(f"card unresolvable: {exc}") from exc

        streaming = bool(getattr(getattr(card, "capabilities", None), "streaming", False))
        config = ClientConfig(
            httpx_client=client_http,
            streaming=streaming,
            accepted_output_modes=["text"],
        )
        client = ClientFactory(config).create(card)
        message = Message(
            message_id="mycelium-seat",
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
        )

        chunks: list[str] = []
        try:
            async for response in client.send_message(SendMessageRequest(message=message)):
                chunk = _reply_text(response)
                if chunk:
                    chunks.append(chunk)
        except (A2AClientError, httpx.HTTPError) as exc:
            raise A2aSendError(f"send failed: {exc}") from exc

        reply = "".join(chunks).strip()
        if not reply:
            raise A2aSendError("remote agent returned no text")
        return reply
    finally:
        if owns_client:
            await client_http.aclose()
