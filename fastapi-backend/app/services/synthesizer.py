# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The synthesizer — a cognition engine that summarizes a room's memory.

A second engine ``kind`` alongside the aligner. Where the aligner *converges* a
negotiation, the synthesizer *distills*: on an ``@``-summon it reads the room's
memory namespaces and compiles a single structured markdown summary, then writes
it back as a ``knowledge`` memory (``context/synthesis``) so every agent — and
``memory search`` — can pick it up.

It shares the aligner's design constraints:

* **Dormant by default (zero idle cost).** Nothing runs until a registered
  ``engine`` of kind ``synthesizer`` is summoned through the persister's summon
  seam — no polling, no held LLM connection.
* **One-shot Pi cognition.** The summary is one throwaway ``pi`` turn off the
  event loop (:func:`_pi_complete`), the same pattern as
  :mod:`app.services.plan_compiler`. Fail-soft: a Pi outage logs and writes
  nothing rather than a half-baked summary.
* **Writes through the canonical memory path.** The summary is upserted via the
  same versioned + indexed write every ``memory set`` uses, so it is searchable
  and version-tracked like any other memory.

Unlike the aligner it holds no episode and drives no negotiation — it is a pure
read → summarize → write consumer.
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

# Reuse the aligner's manifest-kind gate and handle-fold implementations.
from app.services import l9
from app.services.aligner import _norm, _registered_engine_kind
from app.services.l9_slim import serialize_content

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)

_AT_MENTION = re.compile(r"@(?=\w)")

# The engine kind this class owns. A summon whose manifest kind differs is
# ignored, so the aligner and the synthesizer can share one summon seam.
ENGINE_KIND = "synthesizer"

# Where the compiled summary lands. ``context/`` is the room's background surface
# (an existing namespace — no new storage concept), and ``synthesis`` is a stable
# slug so each run upserts (version increments) rather than accreting files.
SYNTHESIS_KEY = "context/synthesis"

# Manifest storage — never a knowledge surface to summarize.
_SKIP_PREFIXES = ("agents/",)


def _read_room_memory(room: str) -> list[tuple[str, dict[str, Any], str]]:
    """Every knowledge memory in the room (all namespaces bar ``agents/``).

    Returns ``(key, meta, content)`` newest-first, minus agent manifests and the
    prior synthesis itself (so a re-run summarizes source memory, not its own
    output).
    """
    from app.services.filesystem import get_room_dir, list_memory_files

    entries = list_memory_files(get_room_dir(room))
    return [
        (key, meta, content)
        for key, meta, content in entries
        if not key.startswith(_SKIP_PREFIXES) and key != SYNTHESIS_KEY
    ]


def _build_prompt(
    room: str, entries: list[tuple[str, dict[str, Any], str]], directive: str = ""
) -> str:
    """Assemble the synthesizer prompt. Pure — no I/O, directly unit-testable."""
    blocks = [f"## {key}\n{content.strip()}" for key, _meta, content in entries]
    corpus = "\n\n".join(blocks)
    if directive:
        task = (
            f'The user asked you: "{directive}"\n\n'
            "Respond naturally and helpfully to their request using the room memory as your context. "
            "If they asked for a briefing or summary, provide one. If they asked something else, "
            "answer it based on what you know from the room. Be faithful — never invent facts not "
            "present in the memory below."
        )
    else:
        task = (
            "Produce a single concise, well-structured markdown briefing that captures the "
            "room's current state: key decisions, current status, open work, and any notable "
            "context. Group related points; do not just list the memories back. Preserve "
            "@handle owners where they matter. Be faithful — never invent facts not present below."
        )
    return (
        f"You are the synthesizer for the Mycelium coordination room '{room}'.\n"
        f"Below are the room's memories, each under its namespace key.\n\n{task}\n\n"
        "Output ONLY your response as markdown — no preamble, no code fences.\n\n"
        f"--- ROOM MEMORY ---\n{corpus}\n--- END ROOM MEMORY ---"
    )


def _strip_fences(text: str) -> str:
    """Drop a wrapping ``` fence if the model added one despite instructions."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _pi_complete(prompt: str, timeout_s: float) -> str:
    """One blocking Pi turn producing the raw summary markdown.

    A throwaway ``--session`` file keeps it a true one-shot with no memory to
    carry — the same pattern as :func:`app.services.plan_compiler._pi_complete`.
    Isolated so tests can patch it without a live Pi.
    """
    from app.services.pi_brain import PiBrain

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    brain = PiBrain(
        session_path=session_dir / f"synthesize-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=timeout_s,
        openshell=settings.ALIGNER_PI_OPENSHELL,
    )
    return brain(prompt)


class SynthesizerEngine:
    """Read a room's memory on summon and write back a structured summary.

    Holds no state between summons beyond the set of rooms it is actively
    summarizing (so a second summon can't spawn a duplicate run over the same
    room). Reaches the channel/membership through the
    :class:`RoomChannelManager` it is wired to, and the memory store through the
    filesystem services.
    """

    def __init__(
        self,
        manager: RoomChannelManager,
        *,
        handle: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._manager = manager
        self._handle = handle if handle is not None else settings.SYNTHESIZER_HANDLE
        self._timeout_s = timeout_s if timeout_s is not None else settings.SYNTHESIZER_PI_TIMEOUT_S
        # Rooms with a run in flight — a re-summon while active is ignored.
        self._active: set[str] = set()
        # Strong refs to scheduled runs so they aren't GC'd mid-flight.
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
        """Fire the synthesizer when a registered ``engine`` (kind
        ``synthesizer``) is summoned; else ignore.

        The persister fires this for every ``@``-mention, so the manifest-kind
        gate is what keeps an ``@teammate`` (or the aligner's summon) from
        spawning a synthesis. There is no reserved-handle fallback: the
        synthesizer is only ever a registered engine.
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
        if room in self._active:
            logger.debug("synthesizer already active on room %s; ignoring re-summon", room)
            return
        self._active.add(room)
        # Strip the @handle prefix so only the user's actual request reaches Pi.
        directive = _AT_MENTION.sub("", message_text).strip()
        task = asyncio.create_task(self._run_and_release(room, handle, directive))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(self, room: str, engine_handle: str, directive: str = "") -> None:
        try:
            await self.synthesize(room, engine_handle=engine_handle, directive=directive)
        except Exception:
            logger.exception("synthesizer run failed on room %s", room)
        finally:
            self._active.discard(room)

    # -- the one path: read → summarize → write --

    async def synthesize(
        self, room: str, engine_handle: str | None = None, directive: str = ""
    ) -> str | None:
        """Compile the room's memory into a ``knowledge`` summary; return it.

        Returns the summary markdown on success, or ``None`` when there is
        nothing to summarize or the Pi turn fails (fail-soft — no partial
        summary is written).
        """
        me = engine_handle or self._handle
        managed = self._manager.get(room)
        entries = _read_room_memory(room)
        if not entries:
            logger.info("synthesizer: room %s has no memory to summarize", room)
            if managed is not None:
                await self._say(
                    managed, room, me, "No memories to summarize yet — post some context first."
                )
            return None

        prompt = _build_prompt(room, entries, directive)
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_pi_complete, prompt, self._timeout_s),
                timeout=self._timeout_s + 5.0,
            )
        except Exception:
            logger.exception("synthesizer: Pi turn failed for room %s", room)
            if managed is not None:
                await self._say(managed, room, me, "Pi turn timed out or errored — try again.")
            return None

        response = _strip_fences(raw or "")
        if not response.strip():
            logger.warning("synthesizer: Pi returned empty response for room %s", room)
            if managed is not None:
                await self._say(managed, room, me, "Pi returned an empty response — try again.")
            return None

        await self._write_summary(room, response, me)
        logger.info(
            "synthesizer: wrote %s for room %s (%d memories)", SYNTHESIS_KEY, room, len(entries)
        )
        if managed is not None:
            await self._say(managed, room, me, response)
        return response

    async def _say(self, managed: ManagedRoomChannel, room: str, sender: str, text: str) -> None:
        """Post a plain message from the synthesizer into the room channel."""
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
            logger.warning("synthesizer failed to broadcast message on room %s", room)
        if managed.persister is not None:
            managed.persister.ingest_local(env, content)

    async def _write_summary(self, room: str, summary: str, created_by: str) -> None:
        """Upsert the summary through the canonical versioned + indexed path."""
        # Lazy import to avoid circular dependency. ``upsert_memories`` is the
        # canonical path for a correct versioned + indexed write.
        from app.routes.memory import upsert_memories
        from app.schemas import MemoryBatchCreate, MemoryCreate

        await upsert_memories(
            room,
            MemoryBatchCreate(
                items=[
                    MemoryCreate(
                        key=SYNTHESIS_KEY,
                        value=summary.rstrip("\n") + "\n",
                        created_by=created_by,
                        embed=True,
                        tags=["synthesis"],
                    )
                ]
            ),
        )
