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

**Honest scope boundary (keep it honest here + in the user-facing docs).** A
bridged A2A agent is **not** a member of the room's MLS group channel — it never
holds a group key. It is proxied by this backend seat, which reads the room's
plaintext (as moderator/custodian) and calls the remote agent out-of-band. Today
that hop is plain HTTPS; it *can* be moved onto SLIM (SLIMRPC, SLIM-identity
authenticated + encrypted) via ``agntcy/slim-a2a-python`` — but even then it is
point-to-point RPC to a distinct SLIM identity, **not** room-group membership
(see #726). Either way the hub is the translation boundary and sees plaintext,
so this is **NOT** E2E-from-the-hub. Auth to the remote is a bearer token whose
value lives in the backend env (``a2a_auth_env`` names the var); the room
manifest never stores the secret.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import yaml
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.types import Message, Part, Role, SendMessageRequest, StreamResponse

from app.services import a2a_activity, l9
from app.services.a2a_card import A2aCardError, resolve_raw_card
from app.services.agent_registry import norm_handle
from app.services.l9_slim import serialize_content
from app.services.persister import envelope_message_id, envelope_sender

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import RoomChannelManager

logger = logging.getLogger(__name__)

_SEND_TIMEOUT_S = 120.0


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


@dataclass(frozen=True)
class A2aAgentRef:
    """A registered a2a agent's call config: where to reach it and how to auth."""

    card: str
    #: Name of the backend env var holding the bearer token, if the remote needs
    #: auth. The secret itself is NEVER stored in the room manifest (it's readable
    #: room memory) — only the env var name is, and it's resolved at send time.
    auth_env: str | None = None
    #: The RPC endpoint resolved from the card at registration, for telemetry —
    #: the send path still resolves the card itself.
    endpoint: str | None = None
    #: Sender handles that may summon this agent (empty = anyone). Normalised to
    #: lowercase without '@' so comparisons are consistent with the gate check.
    allow_from: tuple[str, ...] = ()


def resolve_a2a_agent(room: str, handle: str) -> A2aAgentRef | None:
    """Call config if ``handle`` is a registered ``a2a`` agent in ``room``, else None.

    Mirrors the aligner's engine gate: reads the ``agents/<handle>`` manifest and
    acts only for an ``adapter: a2a`` manifest, so summoning a teammate, engine,
    or unknown handle never fires the bridge.
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
    if not (isinstance(data, dict) and data.get("adapter") == "a2a"):
        return None
    card = data.get("a2a_card")
    if not (isinstance(card, str) and card):
        return None
    env = data.get("a2a_auth_env")
    endpoint = data.get("a2a_endpoint")
    raw_allow = data.get("allow_from") or []
    allow_from: tuple[str, ...] = tuple(
        h for raw in (raw_allow if isinstance(raw_allow, list) else []) if (h := norm_handle(raw))
    )
    return A2aAgentRef(
        card=card,
        auth_env=env if isinstance(env, str) and env else None,
        endpoint=endpoint if isinstance(endpoint, str) and endpoint else None,
        allow_from=allow_from,
    )


def registered_a2a_card(room: str, handle: str) -> str | None:
    """The card URL if ``handle`` is a registered ``a2a`` agent, else None."""
    ref = resolve_a2a_agent(room, handle)
    return ref.card if ref else None


class A2aSendError(Exception):
    """A round-trip to the remote A2A agent failed."""


@dataclass(frozen=True)
class A2aReply:
    """A remote agent's answer plus the conversation id to thread the next turn."""

    text: str
    context_id: str | None = None


def _parts_text(parts: Any) -> str:
    return "".join(p.text for p in (parts or []) if p.HasField("text"))


def _collect(response: StreamResponse) -> tuple[str, str | None]:
    """Text + context id from one A2A stream response, across all payload shapes.

    A remote agent may answer as a bare ``message``, or as a ``task`` (text in
    its artifacts / status message), or stream ``status_update`` /
    ``artifact_update`` events. We read text from whichever arrived and pick up
    the ``context_id`` so the next turn threads the same conversation.
    """
    has = getattr(response, "HasField", lambda _f: False)
    if has("message"):
        m = response.message
        return _parts_text(m.parts), (m.context_id or None)
    if has("task"):
        tk = response.task
        chunks = [_parts_text(a.parts) for a in (tk.artifacts or [])]
        if tk.status.HasField("message"):
            chunks.append(_parts_text(tk.status.message.parts))
        return " ".join(c for c in chunks if c), (tk.context_id or None)
    if has("status_update"):
        su = response.status_update
        text = _parts_text(su.status.message.parts) if su.status.HasField("message") else ""
        return text, (su.context_id or None)
    if has("artifact_update"):
        au = response.artifact_update
        return _parts_text(au.artifact.parts), (au.context_id or None)
    return "", None


async def send_to_a2a(
    card_url: str,
    text: str,
    *,
    context_id: str | None = None,
    auth_token: str | None = None,
    http: httpx.AsyncClient | None = None,
    timeout_s: float = _SEND_TIMEOUT_S,
) -> A2aReply:
    """Send ``text`` to the A2A agent at ``card_url`` and return its reply.

    Pass ``context_id`` (from a prior :class:`A2aReply`) to continue the same
    conversation, so the remote agent keeps its own memory of the thread. Pass
    ``auth_token`` to send it as a bearer credential (for agents whose card
    declares a security scheme). Raises :class:`A2aSendError` on an unresolvable
    card or a failed exchange, so the caller can fall back faithfully (silence,
    never a fabricated reply).
    """
    owns_client = http is None
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
    client_http = http or httpx.AsyncClient(timeout=timeout_s, headers=headers)
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
            message_id=uuid4().hex,
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
        )
        if context_id:
            message.context_id = context_id

        chunks: list[str] = []
        thread: str | None = context_id
        try:
            async for response in client.send_message(SendMessageRequest(message=message)):
                chunk, ctx = _collect(response)
                if chunk:
                    chunks.append(chunk)
                if ctx:
                    thread = ctx
        except (A2AClientError, httpx.HTTPError) as exc:
            raise A2aSendError(f"send failed: {exc}") from exc

        reply = " ".join(c for c in chunks if c).strip()
        if not reply:
            raise A2aSendError("remote agent returned no text")
        return A2aReply(text=reply, context_id=thread)
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
        self._active: set[tuple[str, str | None, str]] = set()
        self._tasks: set[asyncio.Task[Any]] = set()
        # (room, handle) -> A2A context id, so each mention continues the same
        # remote conversation instead of starting cold. In-memory: a restart
        # resets threads (the room transcript is still the durable record).
        self._threads: dict[tuple[str | None, str | None, str | None], str] = {}

    # -- the summon seam (sync; called from the persister's on_summon) --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: L9,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        ref = resolve_a2a_agent(room, handle)
        if ref is None:
            return  # not an a2a agent — let the engines / a teammate handle it
        sender = envelope_sender(envelope)
        if norm_handle(sender) == norm_handle(handle):
            return  # never answer our own message (loop guard)
        # Runaway guard: an a2a agent's auto-reply must not summon another a2a
        # agent. Two agents that mention each other would otherwise ping-pong
        # forever, each hop a real remote call. Humans, the aligner, and resident
        # agents still trigger a reply; only registered-a2a -> registered-a2a is cut.
        if sender and resolve_a2a_agent(room, sender) is not None:
            logger.debug("a2a responder: skip @%s summoned by a2a agent @%s", handle, sender)
            return
        # Summon gate: if the manifest names an allow_from list, only those
        # handles may trigger a remote call (and spend its bearer token / quota).
        if ref.allow_from and norm_handle(sender) not in ref.allow_from:
            logger.debug(
                "a2a responder: @%s not in allow_from for @%s — ignoring summon", sender, handle
            )
            return
        prompt = (message_text or "").strip()
        if not prompt:
            return
        mid = envelope_message_id(envelope) or ""
        key = (room, norm_handle(handle), mid)
        if key in self._active:
            return
        self._active.add(key)
        # Resolve the bearer credential from the backend env (the manifest holds
        # only the var name), so the secret never lives in room memory. A declared
        # but missing var is a misconfiguration — fail closed so it appears in the
        # Network pane rather than silently calling the remote unauthenticated.
        token: str | None = None
        if ref.auth_env:
            token = os.environ.get(ref.auth_env)
            if token is None:
                logger.warning(
                    "a2a responder: auth_env '%s' is set on @%s but the env var is missing; "
                    "refusing unauthenticated call",
                    ref.auth_env,
                    handle,
                )
                # Record the misconfiguration through the activity path so the
                # Network pane shows it rather than leaving silence unexplained.
                a2a_activity.record_outbound(
                    room,
                    handle,
                    endpoint=ref.endpoint or ref.card,
                    peer=sender,
                    prompt=(message_text or "").strip(),
                    status="error",
                    detail=f"auth_env '{ref.auth_env}' declared but not set in the backend environment",
                    duration_ms=0,
                )
                self._active.discard(key)
                return
        task = asyncio.create_task(
            self._run_and_release(room, handle, ref, prompt, envelope, key, token)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(
        self,
        room: str,
        handle: str,
        ref: A2aAgentRef,
        prompt: str,
        envelope: L9,
        key: tuple[str, str | None, str],
        auth_token: str | None = None,
    ) -> None:
        summoner = envelope_sender(envelope)
        # Thread context is per summoner: two members addressing the same remote
        # agent must not share one remote contextId (context bleed). In-memory
        # only — a restart resets threads, but the room transcript is durable.
        thread_key = (room, norm_handle(handle), norm_handle(summoner))
        # Name the speaker so the remote agent can follow a multi-party room; the
        # threaded context id carries the rest of the history on the remote side.
        addressed = f"@{norm_handle(summoner)}: {prompt}" if summoner else prompt
        # Telemetry for the Network views: the bridge hop leaves no trace on the
        # channel, so both outcomes are recorded here (#739).
        started = time.monotonic()
        recorded = partial(
            a2a_activity.record_outbound,
            room,
            handle,
            endpoint=ref.endpoint or ref.card,
            peer=summoner,
            prompt=prompt,
        )
        try:
            reply = await send_to_a2a(
                ref.card,
                addressed,
                context_id=self._threads.get(thread_key),
                auth_token=auth_token,
                timeout_s=self._timeout_s,
            )
            if reply.context_id:
                self._threads[thread_key] = reply.context_id
            recorded(status="ok", reply=reply.text, duration_ms=_elapsed_ms(started))
            await self._respond(room, handle, reply.text, envelope)
        except A2aSendError as exc:
            # Fail-faithful: a dead/unreadable remote posts nothing rather than a
            # fabricated reply. The caller (human or aligner) sees silence — the
            # Network pane is where that silence is legible as a failed call.
            recorded(status="error", detail=str(exc), duration_ms=_elapsed_ms(started))
            logger.warning("a2a responder: @%s in %s did not answer", handle, room)
        except Exception as exc:
            recorded(status="error", detail=str(exc), duration_ms=_elapsed_ms(started))
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
