# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The hello engine — a cognition engine that proves the summon path.

A third engine ``kind`` alongside the aligner and the synthesizer, and the only
one that owns nothing. On an ``@``-summon it runs one Pi turn on whatever was
said and posts the answer back into the room: no episode, no memory write, no
plan, no state carried between summons. The only trace it leaves is the message
it posts.

That is the point. The aligner and the synthesizer both do real work with real
side effects, so neither is something to fire into a shared room just to check
the wiring — and so the engine path stays unproven until something important
needs it. A summon of a ``hello`` engine walks every rung: the manifest-kind
gate, the :data:`~app.config.Settings.ENGINE_RUNTIME` branch, the self-summon
guard, a :class:`~app.services.pi_brain.PiBrain` one-shot, and the channel send
plus persister ingest. A reply in the room means all of it works; silence
narrows the failure to one place.

It shares the other engines' design constraints: dormant by default (nothing
runs until a registered engine of kind ``hello`` is summoned), one throwaway Pi
turn off the event loop, and fail-loud into the room — a timeout or an error
posts a readable reason rather than going quiet, since a probe that fails
silently is worse than no probe.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import settings

# Reuse the aligner's manifest-kind gate and handle-fold, and the synthesizer's
# fence-stripping, rather than growing a third copy of each.
from app.services import l9
from app.services.aligner import _norm, _registered_engine_kind
from app.services.l9_slim import serialize_content
from app.services.synthesizer import _strip_fences

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)

_AT_MENTION = re.compile(r"@(?=\w)")

# The engine kind this class owns. A summon whose manifest kind differs is
# ignored, so every engine can share one summon seam.
ENGINE_KIND = "hello"

# What a bare ``@hello`` (no text after the mention) asks for.
DEFAULT_DIRECTIVE = (
    "Say hello, name the model you are running as, and confirm the engine path works."
)


def _build_prompt(room: str, handle: str, directive: str) -> str:
    """Assemble the hello prompt. Pure — no I/O, directly unit-testable."""
    return (
        f"You are @{handle}, a cognition engine in the Mycelium coordination room '{room}'.\n"
        "You hold no state between summons and own no memory: someone mentions you, you "
        "answer once, and that is the whole interaction.\n\n"
        f'Someone said to you: "{directive or DEFAULT_DIRECTIVE}"\n\n'
        "Answer them directly and briefly — a few sentences at most. Output ONLY your "
        "reply as plain markdown: no preamble, no code fences."
    )


def _pi_complete(prompt: str, timeout_s: float) -> str:
    """One blocking Pi turn producing the raw reply text.

    A throwaway ``--session`` file keeps it a true one-shot with no memory to
    carry — the same pattern as :func:`app.services.synthesizer._pi_complete`.
    Isolated so tests can patch it without a live Pi.
    """
    from app.services.pi_brain import PiBrain

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    brain = PiBrain(
        session_path=session_dir / f"hello-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=timeout_s,
        openshell=settings.ALIGNER_PI_OPENSHELL,
    )
    return brain(prompt)


class HelloEngine:
    """Answer a summon with one Pi turn, and write nothing anywhere.

    Reaches the room's channel through the :class:`RoomChannelManager` it is
    wired to. The only state it holds is the set of ``(room, handle)`` pairs
    with a turn in flight, so a re-summon can't stack duplicate Pi turns on the
    same engine — a second hello engine in the same room is unaffected.
    """

    def __init__(
        self,
        manager: RoomChannelManager,
        *,
        handle: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._manager = manager
        self._handle = handle if handle is not None else settings.HELLO_HANDLE
        self._timeout_s = timeout_s if timeout_s is not None else settings.HELLO_PI_TIMEOUT_S
        # (room, handle) pairs with a turn in flight — a re-summon is ignored.
        self._active: set[tuple[str, str]] = set()
        # Strong refs to scheduled turns so they aren't GC'd mid-flight.
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def handle(self) -> str:
        return self._handle

    # -- the summon seam (sync; called from the persister's on_summon) --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: L9,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        """Fire the hello engine when a registered ``engine`` (kind ``hello``)
        is summoned; else ignore.

        The persister fires this for every ``@``-mention, so the manifest-kind
        gate is what keeps an ``@teammate`` — or another engine's summon — from
        spawning a Pi turn. There is no reserved-handle fallback: hello is only
        ever a registered engine.
        """
        if _registered_engine_kind(room, handle) != ENGINE_KIND:
            return
        # When ENGINE_RUNTIME=host the host daemon owns a registered engine's run.
        if settings.ENGINE_RUNTIME == "host":
            logger.info(
                "engine @%s summoned in %s but ENGINE_RUNTIME=host — host daemon owns the run",
                handle,
                room,
            )
            return
        from app.services.persister import envelope_sender

        sender = envelope_sender(envelope)
        if sender is not None and _norm(sender) in {_norm(self._handle), _norm(handle)}:
            return  # never summon off our own message
        key = (room, _norm(handle))
        if key in self._active:
            logger.debug("hello @%s already answering in %s; ignoring re-summon", handle, room)
            return
        self._active.add(key)
        # Strip the @handle prefix so only what was actually said reaches Pi.
        directive = _AT_MENTION.sub("", message_text).strip()
        task = asyncio.create_task(self._run_and_release(room, handle, directive, key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(
        self, room: str, engine_handle: str, directive: str, key: tuple[str, str]
    ) -> None:
        try:
            await self.greet(room, engine_handle=engine_handle, directive=directive)
        except Exception:
            logger.exception("hello @%s failed in room %s", engine_handle, room)
        finally:
            self._active.discard(key)

    # -- the one path: read the summon → one Pi turn → say it --

    async def greet(
        self, room: str, engine_handle: str | None = None, directive: str = ""
    ) -> str | None:
        """Answer ``directive`` with one Pi turn and post it; return the reply.

        Returns ``None`` when the Pi turn fails or comes back empty — in which
        case the reason is posted into the room instead, so a probe never fails
        silently.
        """
        me = engine_handle or self._handle
        managed = self._manager.get(room)
        prompt = _build_prompt(room, me, directive)
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_pi_complete, prompt, self._timeout_s),
                timeout=self._timeout_s + 5.0,
            )
        except Exception:
            logger.exception("hello: Pi turn failed for room %s", room)
            await self._say(managed, room, me, "Pi turn timed out or errored — try again.")
            return None

        reply = _strip_fences(raw or "")
        if not reply.strip():
            logger.warning("hello: Pi returned an empty response for room %s", room)
            await self._say(managed, room, me, "Pi returned an empty response — try again.")
            return None

        logger.info("hello: @%s answered a summon in room %s", me, room)
        await self._say(managed, room, me, reply)
        return reply

    async def _say(
        self, managed: ManagedRoomChannel | None, room: str, sender: str, text: str
    ) -> None:
        """Post a plain message from the engine into the room channel."""
        if managed is None:
            logger.warning("hello: no channel for room %s; dropping reply", room)
            return
        env = l9.build_envelope(
            kind=l9.Kind.exchange,
            episode=l9.episode_urn(room, "live"),
            sender=sender,
            topic=l9.topic_urn(room),
            payload_type="message",
        )
        content = serialize_content(env, extra={"content": text})
        try:
            await managed.channel.send(env, extra={"content": text})
        except Exception:
            logger.warning("hello failed to broadcast message on room %s", room)
        if managed.persister is not None:
            managed.persister.ingest_local(env, content)
