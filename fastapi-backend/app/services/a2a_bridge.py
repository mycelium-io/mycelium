# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Drive a registered A2A agent as a backend-held room member (epic #719, #714).

Two pieces:

- :func:`send_to_a2a` — the client leg: given a remote agent's card URL and a
  prompt, call it over A2A and return its reply text.
- :class:`A2aResponder` — the seat: an event-driven ``@``-mention responder
  wired to the persister's ``on_summon`` seam (the same one the engines use). It
  does *not* poll and is not coupled to negotiation. When someone ``@``-mentions
  a registered ``a2a`` agent in normal chat, it calls the remote and posts the
  reply back as that handle. The aligner addressing the agent mid-negotiation is
  just one caller that happens to ``@``-mention it.

The send path carries the #712 spike findings: resolve the card (dual well-known
path), then build a client with ``accepted_output_modes`` set — without it,
older servers reject the send with a pydantic ``-32600``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import httpx
import yaml
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.types import Message, Part, Role, SendMessageRequest

from app.services import l9
from app.services.a2a_card import A2aCardError, resolve_raw_card
from app.services.l9_slim import serialize_content
from app.services.persister import envelope_message_id, envelope_sender

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import RoomChannelManager

logger = logging.getLogger(__name__)

_SEND_TIMEOUT_S = 120.0


def _norm(handle: str | None) -> str:
    return (handle or "").strip().lstrip("@").lower()


def registered_a2a_card(room: str, handle: str) -> str | None:
    """The card URL if ``handle`` is a registered ``a2a`` agent in ``room``.

    Mirrors the aligner's engine gate: reads the ``agents/<handle>`` manifest and
    returns its ``a2a_card`` only for an ``adapter: a2a`` manifest, else ``None``
    — so summoning a teammate, engine, or unknown handle never fires the bridge.
    """
    from app.services.filesystem import get_room_dir, read_memory_file

    result = read_memory_file(get_room_dir(room), f"agents/{handle}")
    if result is None:
        return None
    _meta, body = result
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        return None
    if isinstance(data, dict) and data.get("adapter") == "a2a":
        card = data.get("a2a_card")
        return card if isinstance(card, str) and card else None
    return None


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


class A2aResponder:
    """Answer ``@``-mentions of a registered A2A agent by calling the remote.

    Wired onto the same summon seam as the engines: the persister fires
    ``on_summon`` for every ``@``-mention, and this responder acts only when the
    mentioned handle is a registered ``a2a`` agent. It calls the remote agent
    with the message text and posts the reply back as that handle — normal chat
    flow, no polling and no negotiation coupling. The aligner addressing the
    agent mid-negotiation is just one caller that happens to ``@``-mention it.
    """

    def __init__(self, manager: RoomChannelManager, *, timeout_s: float = _SEND_TIMEOUT_S) -> None:
        self._manager = manager
        self._timeout_s = timeout_s
        # (room, handle, message_id) currently in flight — a re-fire is ignored.
        self._active: set[tuple[str, str, str]] = set()
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- the summon seam (sync; called from the persister's on_summon) --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: L9,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        card = registered_a2a_card(room, handle)
        if card is None:
            return  # not an a2a agent — let the engines / a teammate handle it
        sender = envelope_sender(envelope)
        if _norm(sender) == _norm(handle):
            return  # never answer our own message (loop guard)
        prompt = (message_text or "").strip()
        if not prompt:
            return
        mid = envelope_message_id(envelope) or ""
        key = (room, _norm(handle), mid)
        if key in self._active:
            return
        self._active.add(key)
        task = asyncio.create_task(self._run_and_release(room, handle, card, prompt, envelope, key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(
        self,
        room: str,
        handle: str,
        card: str,
        prompt: str,
        envelope: L9,
        key: tuple[str, str, str],
    ) -> None:
        try:
            reply = await send_to_a2a(card, prompt, timeout_s=self._timeout_s)
            await self._respond(room, handle, reply, envelope)
        except A2aSendError:
            # Fail-faithful: a dead/unreadable remote posts nothing rather than a
            # fabricated reply. The caller (human or aligner) sees silence.
            logger.warning("a2a responder: @%s in %s did not answer", handle, room)
        except Exception:
            logger.exception("a2a responder run failed for @%s in %s", handle, room)
        finally:
            self._active.discard(key)

    async def _respond(self, room: str, handle: str, text: str, in_reply_to: L9) -> None:
        """Post ``text`` into the room as ``handle``, addressed to the summoner."""
        managed = self._manager.get(room)
        if managed is None:
            return
        summoner = envelope_sender(in_reply_to)
        parent = envelope_message_id(in_reply_to)
        env = l9.build_envelope(
            kind=l9.Kind.exchange,
            episode=l9.episode_urn(room, "live"),
            parents=[parent] if parent else None,
            sender=handle,
            sender_role="agent",
            recipients=[summoner] if summoner else None,
            topic=l9.topic_urn(room),
            payload_type="reply",
        )
        content = serialize_content(env, extra={"content": text})
        try:
            await managed.channel.send(env, extra={"content": text})
        except Exception:
            logger.warning("a2a responder failed to broadcast @%s reply on %s", handle, room)
        if managed.persister is not None:
            managed.persister.ingest_local(env, content, list_write=True)
        # Best-effort presence: a handle that just answered is live in the room.
        try:
            self._manager.refresh_lease(room, handle)
        except Exception:
            logger.debug("a2a responder: lease refresh skipped for @%s in %s", handle, room)
