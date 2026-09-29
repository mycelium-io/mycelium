# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The persona engine — a room member played by a model, in character.

A fifth engine ``kind``. Where hello answers once and forgets, a persona is a
standing member with a character: the persona text written to its
``agents/<handle>/notes`` memory is the system prompt of every turn, and its
Pi session is kept per handle, so it remembers what it said last time it was
asked. Register one per character a demonstration needs (a cautious
guardian, a proposer with a deadline, a supplier with limited stock), seed
each one's notes, and the room has members that answer without a resident
session behind any of them.

It answers on two seams. A text ``@``-mention is a summon, like any engine's.
An **addressed turn** — an exchange naming it as an L9 recipient with nobody
mentioned in the text, which is how the aligner and the conductor put a
question to one member — reaches it through the persister's addressed hook,
so a persona can fill a protocol role or a negotiation seat. Either way it
answers where it was asked, in the thread the turn rode.

A reply ending in a position marker is lifted the way the reply route lifts
one: the stance lands on the L9 payload and the prose is posted clean, so a
guardian played by a persona blocks a gated step the same as a resident agent
would. Every ``@`` in what it says is neutralized before posting, so a persona
can never summon anything, and two personas cannot ping-pong.

Dormant by default and fail-loud like the other engines: a Pi error or an
empty answer is posted as a readable reason rather than silence.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services import activity, l9, markers, turns
from app.services.aligner import _norm, _registered_engine_kind
from app.services.l9_models import Kind
from app.services.synthesizer import _strip_fences

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)

#: The engine kind this class owns.
ENGINE_KIND = "persona"

#: Where a persona's character lives: the notes memory every agent has.
NOTES_SUFFIX = "/notes"

#: What a persona with no notes and no description is told it is.
DEFAULT_PERSONA = (
    "You are a thoughtful member of a working team. You have opinions, you state "
    "them plainly, and you change your mind when given a good reason."
)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _build_prompt(room: str, handle: str, sender: str, text: str, *, in_thread: bool) -> str:
    """Assemble the turn prompt. Pure — no I/O, directly unit-testable."""
    where = "in a task's thread" if in_thread else "in the room"
    return (
        f"You are @{handle}, a member of the Mycelium coordination room '{room}', "
        f"speaking {where}. Stay in character as described in your instructions.\n\n"
        f"{sender} said to you:\n\n{text}\n\n"
        "Reply directly, in a few sentences, as plain markdown with no preamble and no "
        "code fences. Do not put @ in front of anyone's name. If you are being asked "
        "to approve or block something, end your reply with exactly one of "
        "[[mycelium: stance=accept]] or [[mycelium: stance=reject]]; if you are "
        "stating a position in a negotiation, end with [[mycelium: confidence=<0-1>]]."
    )


def _persona_text(room: str, handle: str) -> str:
    """The character a persona plays: its notes, else its description, else the default."""
    import yaml

    from app.services.filesystem import get_room_dir, read_memory_file

    room_dir = get_room_dir(room)
    notes = read_memory_file(room_dir, f"agents/{handle}{NOTES_SUFFIX}")
    if notes is not None and notes[1].strip():
        return notes[1].strip()
    manifest = read_memory_file(room_dir, f"agents/{handle}")
    if manifest is not None:
        try:
            data = yaml.safe_load(manifest[1]) or {}
        except yaml.YAMLError:
            data = {}
        description = data.get("description") if isinstance(data, dict) else None
        if isinstance(description, str) and description.strip():
            return description.strip()
    return DEFAULT_PERSONA


def _session_path(room: str, handle: str) -> Path:
    """One session file per (room, handle), so a persona remembers across turns."""
    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    slug = _UNSAFE.sub("-", f"persona-{room}-{handle}").strip("-")
    return session_dir / f"{slug}.jsonl"


def _pi_complete(room: str, handle: str, prompt: str, system: str, timeout_s: float) -> str:
    """One blocking Pi turn on the persona's own persistent session.

    Isolated so tests can patch it without a live Pi.
    """
    from app.services.pi_session import PiSession

    llm_session = PiSession(
        session_path=_session_path(room, handle),
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=timeout_s,
        openshell=settings.ALIGNER_PI_OPENSHELL,
    )
    return llm_session(prompt, system=system)


class PersonaEngine:
    """Answer a mention or an addressed turn in character, and remember it."""

    def __init__(
        self,
        manager: RoomChannelManager,
        *,
        handle: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._manager = manager
        self._handle = handle if handle is not None else settings.PERSONA_HANDLE
        self._timeout_s = timeout_s if timeout_s is not None else settings.PERSONA_PI_TIMEOUT_S
        # (room, handle) pairs with a turn in flight — a second ask waits for no
        # one; it is dropped, and the asker's timeout says so.
        self._active: set[tuple[str, str]] = set()
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def handle(self) -> str:
        return self._handle

    # -- the two seams --

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: L9,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        """A text mention of a registered persona: answer it.

        Unless the same text summons a conductor: the handles named beside one
        are bound to its roles, not asked a question, and the conductor will
        address each in its turn. Answering the summon would talk over the
        floor it just took, and leave the persona busy when its real turn came.
        """
        for other in co_summons or ():
            if (
                _norm(other) != _norm(handle)
                and _registered_engine_kind(room, other) == "conductor"
            ):
                return
        self._fire(room, handle, envelope, message_text)

    def handle_addressed(self, room: str, handle: str, envelope: L9, message_text: str) -> None:
        """An addressed turn naming a registered persona as recipient: answer it."""
        self._fire(room, handle, envelope, message_text)

    def _fire(self, room: str, handle: str, envelope: L9, message_text: str) -> None:
        if _registered_engine_kind(room, handle) != ENGINE_KIND:
            return
        if settings.ENGINE_RUNTIME == "host":
            logger.info("engine @%s summoned in %s but ENGINE_RUNTIME=host", handle, room)
            return
        from app.services.persister import envelope_sender

        sender = envelope_sender(envelope)
        if sender is None or _norm(sender) in {_norm(self._handle), _norm(handle)}:
            return
        key = (room, _norm(handle))
        if key in self._active:
            logger.debug("persona @%s already answering in %s; dropping this ask", handle, room)
            return
        self._active.add(key)
        episode = (envelope.header.message.episode if envelope.header.message else None) or ""
        text = turns.neutralize_mentions(message_text).strip()
        task = asyncio.create_task(
            self._run_and_release(
                room, handle, episode or l9.live_episode_urn(room), sender, text, key
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(
        self,
        room: str,
        handle: str,
        episode: str,
        sender: str,
        text: str,
        key: tuple[str, str],
    ) -> None:
        try:
            await self.answer(room, engine_handle=handle, episode=episode, sender=sender, text=text)
        except Exception:
            logger.exception("persona @%s failed in room %s", handle, room)
        finally:
            self._active.discard(key)

    # -- the one path: persona + what was said → one Pi turn → say it --

    async def answer(
        self,
        room: str,
        *,
        engine_handle: str | None = None,
        episode: str | None = None,
        sender: str = "someone",
        text: str = "",
    ) -> str | None:
        """Answer ``text`` in character and post it into ``episode``; return the prose.

        ``None`` when the Pi turn fails or comes back empty, in which case the
        reason is posted instead so a silent persona never looks like a
        thinking one.
        """
        me = engine_handle or self._handle
        managed = self._manager.get(room)
        where = episode or l9.live_episode_urn(room)
        in_thread = not l9.is_live_episode(room, where)
        system = _persona_text(room, me)
        prompt = _build_prompt(room, me, sender, text, in_thread=in_thread)
        activity.signal(room, me, "responding", episode=where)
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_pi_complete, room, me, prompt, system, self._timeout_s),
                timeout=self._timeout_s + 5.0,
            )
        except Exception:
            logger.exception("persona @%s: Pi turn failed in room %s", me, room)
            await self._say(managed, where, me, "Pi turn timed out or errored; ask me again.")
            return None
        finally:
            activity.signal(room, me, "done", episode=where)

        reply = _strip_fences(raw or "")
        if not reply.strip():
            logger.warning("persona @%s: Pi returned an empty response in %s", me, room)
            await self._say(managed, where, me, "Pi returned an empty response; ask me again.")
            return None
        payload, clean = markers.parse_marker(reply)
        clean = turns.neutralize_mentions(clean)
        await self._say(managed, where, me, clean, payload=payload)
        return clean

    async def _say(
        self,
        managed: ManagedRoomChannel | None,
        episode: str,
        sender: str,
        text: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Post ``text`` as the persona into ``episode``, a stance on the payload.

        A persona is a member, and a member off the floor does not speak: a
        reply into a thread whose floor was not given to it is dropped, the
        same refusal the write routes answer with a 409.
        """
        if managed is None:
            logger.warning("persona @%s: no channel for room; dropping reply", sender)
            return
        floor = self._manager.floor(managed.room, episode)
        if floor is not None and not floor.admits(sender):
            logger.info("persona @%s is off the floor in %s; not posting", sender, episode)
            return
        env = l9.build_envelope(
            kind=Kind.exchange,
            episode=episode,
            sender=sender,
            sender_role="agent",
            topic=l9.topic_urn(managed.room),
            payload_type="reply",
            payload_data=payload or {"action": "reply"},
        )
        try:
            await managed.post(env, text, list_write=True)
        except Exception:
            logger.warning("persona @%s failed to post on room %s", sender, managed.room)
