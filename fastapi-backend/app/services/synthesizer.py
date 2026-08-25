# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The synthesizer — a cognition engine that distills a room's talk into memory.

A second engine ``kind`` alongside the aligner. Where the aligner *converges* a
negotiation, the synthesizer *distills*: on an ``@``-summon it reads the room's
**transcript** — the ephemeral half, where a decision gets argued, qualified and
settled and where nothing indexes it for meaning — and writes what it learned
into the **durable** half, as a ``knowledge`` memory (``context/synthesis``) that
every agent and ``memory search`` can pick up.

The direction is the point: conversation is the medium that leaks, memory is the
one that keeps, and the engine is the bridge between them. Re-summarizing memory
into memory (:data:`~app.config.SynthesizerSource` ``memory``, the older
behavior) is a different feature — a briefing over what is already durable — and
stays available behind ``SYNTHESIZER_SOURCE``.

Design constraints, shared with the aligner:

* **Dormant by default (zero idle cost).** Nothing runs until a registered
  ``engine`` of kind ``synthesizer`` is summoned through the persister's summon
  seam — no polling, no held LLM connection.
* **One-shot Pi cognition.** The summary is one throwaway ``pi`` turn off the
  event loop (:func:`_pi_complete`), the same pattern as
  :mod:`app.services.task_compiler`. Fail-soft: a Pi outage logs and writes
  nothing rather than a half-baked summary.
* **Writes through the canonical memory path.** The summary is upserted via the
  same versioned + indexed write every ``memory set`` uses, so it is searchable,
  linked and version-tracked like any other memory.

Two properties are specific to reading a live transcript:

* **Incremental by default.** The written memory carries the position it was
  distilled through (:data:`CURSOR_META_KEY` in its own frontmatter, so the
  cursor advances exactly when the output lands). Each run reads only what
  arrived since and folds it into the standing summary; a run with nothing new
  writes nothing. ``--all`` in the summon text re-reads the whole transcript.
* **It never eats its own output.** The synthesizer posts its summary back into
  the room, so its own words are in its next input. Every message from a
  registered synthesizer handle is dropped from the corpus before the prompt is
  built.

Unlike the aligner it holds no episode and drives no negotiation — it is a pure
read → distill → write consumer.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import settings

# Reuse the aligner's manifest-kind gate and handle-fold implementations.
from app.services import l9
from app.services.aligner import _norm, _registered_engine_kind
from app.services.l9_slim import serialize_content

if TYPE_CHECKING:
    from app.services.in_memory_store import StoredMessage
    from app.services.l9_models import L9
    from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

logger = logging.getLogger(__name__)

_AT_MENTION = re.compile(r"@(?=\w)")

# The one override the summon text carries: re-distill the whole transcript
# instead of the slice since the last run. A standalone token, so a sentence that
# merely mentions "all" doesn't trigger a full pass.
_FULL_PASS = re.compile(r"(?:^|\s)--(?:all|full)(?=\s|$)")

# The engine kind this class owns. A summon whose manifest kind differs is
# ignored, so the aligner and the synthesizer can share one summon seam.
ENGINE_KIND = "synthesizer"

# Where the compiled summary lands. ``context/`` is the room's background surface
# (an existing namespace — no new storage concept), and ``synthesis`` is a stable
# slug so each run upserts (version increments) rather than accreting files.
SYNTHESIS_KEY = "context/synthesis"

# The incremental cursor, carried in the summary's own unmanaged frontmatter: the
# last message this memory was distilled through. Living on the output rather than
# in a sidecar file makes the two atomic — a run that writes nothing advances
# nothing, and deleting the summary asks for a full re-read next time.
CURSOR_META_KEY = "synthesized_through"

# Manifest storage — never a knowledge surface to summarize.
_SKIP_PREFIXES = ("agents/",)


def _read_room_memory(room: str) -> list[tuple[str, dict[str, Any], str]]:
    """Every knowledge memory in the room (all namespaces bar ``agents/``).

    The corpus for ``SYNTHESIZER_SOURCE=memory``. Returns ``(key, meta, content)``
    minus agent manifests and the prior synthesis itself.
    """
    from app.services.filesystem import get_room_dir, list_memory_files

    entries = list_memory_files(get_room_dir(room))
    return [
        (key, meta, content)
        for key, meta, content in entries
        if not key.startswith(_SKIP_PREFIXES) and key != SYNTHESIS_KEY
    ]


# ── the transcript corpus ─────────────────────────────────────────────────────


def _own_handles(room: str, senders: set[str], *, me: str) -> set[str]:
    """The senders whose messages are this engine's own output, normalized.

    A synthesizer speaks into the room it reads, so without this its summary is
    the loudest thing in its next corpus. Membership is decided by the room's
    roster — any handle registered as a ``synthesizer`` engine — rather than by
    the one handle this run happens to answer as, so a room that renamed or
    re-registered its synthesizer doesn't start feeding on old summaries.
    """
    own = {_norm(me)}
    own |= {
        _norm(sender)
        for sender in senders
        if _norm(sender) not in own and _registered_engine_kind(room, sender) == ENGINE_KIND
    }
    return own


def _cursor(room: str) -> tuple[str | None, datetime | None]:
    """The position the standing summary was distilled through, if any."""
    from app.services.filesystem import get_room_dir, parse_timestamp, read_memory_file

    existing = read_memory_file(get_room_dir(room), SYNTHESIS_KEY)
    if existing is None:
        return None, None
    cursor = existing[0].get(CURSOR_META_KEY)
    if not isinstance(cursor, dict):
        return None, None
    message_id = cursor.get("message_id")
    return (
        message_id if isinstance(message_id, str) else None,
        parse_timestamp(cursor.get("recorded_at")) if cursor.get("recorded_at") else None,
    )


def _since_cursor(
    messages: list[StoredMessage], cursor_id: str | None, cursor_at: datetime | None
) -> list[StoredMessage]:
    """The tail of ``messages`` after the cursor (all of it when there is none).

    The id is the precise cut and the timestamp is the fallback: a message that
    was in the feed at the last run can drop out of it (an in-memory row lost to
    a restart, a truncated transcript), and without the fallback a missing anchor
    would re-distill the entire room.
    """
    if cursor_id is not None:
        for i, message in enumerate(messages):
            if str(message.id) == cursor_id:
                return messages[i + 1 :]
    if cursor_at is not None:
        return [m for m in messages if m.created_at > cursor_at]
    return messages


def _read_new_messages(room: str, *, me: str, full: bool) -> tuple[list[StoredMessage], int]:
    """The room's undistilled chat, and how many messages the room holds in all.

    Read by type (:func:`app.services.persister.prose_messages`), so a
    coordination tick or a promoted ``l9_*`` frame — whose content is a
    serialized envelope — is excluded structurally rather than by inspecting what
    a payload looks like.
    """
    from app.services.persister import prose_messages

    chat = prose_messages(room)
    own = _own_handles(room, {m.sender_handle for m in chat}, me=me)
    chat = [m for m in chat if _norm(m.sender_handle) not in own]
    if full:
        return chat, len(chat)
    return _since_cursor(chat, *_cursor(room)), len(chat)


def _prior_summary(room: str) -> str:
    """The standing synthesis body, or empty when the room has none yet."""
    from app.services.filesystem import get_room_dir, read_memory_file

    existing = read_memory_file(get_room_dir(room), SYNTHESIS_KEY)
    return existing[1].strip() if existing else ""


def _transcript_block(messages: list[StoredMessage]) -> str:
    """Render the corpus as a plain speaker-tagged log."""
    return "\n".join(
        f"[{m.created_at.isoformat()}] @{m.sender_handle}: {m.content.strip()}" for m in messages
    )


def _build_message_prompt(
    room: str,
    messages: list[StoredMessage],
    prior: str,
    directive: str = "",
) -> str:
    """Assemble the transcript-distilling prompt. Pure — directly unit-testable."""
    if directive:
        task = (
            f'The user asked you: "{directive}"\n\n'
            "Answer them from the conversation below, and produce the room's standing "
            "briefing shaped by what they asked for."
        )
    else:
        task = (
            "Distill this conversation into the room's standing briefing: what was "
            "decided, what changed, what is now in flight, and what is still open. "
            "Group related points; do not transcribe the messages back. Preserve "
            "@handle owners where they matter."
        )
    carried = (
        "The briefing below is what earlier conversation already distilled to. "
        "Fold the new messages into it: keep what still holds, correct what the "
        "conversation has overtaken, and drop nothing that is still true.\n\n"
        f"--- STANDING BRIEFING ---\n{prior}\n--- END STANDING BRIEFING ---\n\n"
        if prior
        else ""
    )
    return (
        f"You are the synthesizer for the Mycelium coordination room '{room}'.\n"
        "Below is new conversation from the room, oldest first, each line tagged "
        "with its sender.\n\n"
        f"{task}\n\n"
        "Be faithful — never invent facts not present in what you were given. "
        "Output ONLY the briefing as markdown — no preamble, no code fences.\n\n"
        f"{carried}"
        f"--- NEW MESSAGES ---\n{_transcript_block(messages)}\n--- END NEW MESSAGES ---"
    )


def _build_prompt(
    room: str, entries: list[tuple[str, dict[str, Any], str]], directive: str = ""
) -> str:
    """Assemble the memory-corpus prompt (``SYNTHESIZER_SOURCE=memory``). Pure."""
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
    carry — the same pattern as :func:`app.services.task_compiler._pi_complete`.
    Isolated so tests can patch it without a live Pi.
    """
    from app.services.pi_session import PiSession

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    llm_session = PiSession(
        session_path=session_dir / f"synthesize-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=timeout_s,
        openshell=settings.ALIGNER_PI_OPENSHELL,
    )
    return llm_session(prompt)


class SynthesizerEngine:
    """Distill a room's conversation into memory on summon.

    Holds no state between summons beyond the set of rooms it is actively
    distilling (so a second summon can't spawn a duplicate run over the same
    room) — the incremental position lives on the written memory, not here.
    Reaches the channel/membership through the :class:`RoomChannelManager` it is
    wired to, and the transcript + memory store through the services.
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
        # Strip the @handle prefix so only the user's actual request reaches Pi,
        # and lift the one flag the summon text carries out of the directive.
        directive = _AT_MENTION.sub("", message_text).strip()
        full = bool(_FULL_PASS.search(directive))
        directive = " ".join(_FULL_PASS.sub(" ", directive).split())
        task = asyncio.create_task(self._run_and_release(room, handle, directive, full))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(
        self, room: str, engine_handle: str, directive: str = "", full: bool = False
    ) -> None:
        try:
            await self.synthesize(room, engine_handle=engine_handle, directive=directive, full=full)
        except Exception:
            logger.exception("synthesizer run failed on room %s", room)
        finally:
            self._active.discard(room)

    # -- the one path: read → distill → write --

    async def synthesize(
        self,
        room: str,
        engine_handle: str | None = None,
        directive: str = "",
        full: bool = False,
    ) -> str | None:
        """Distill the room into a ``knowledge`` summary; return it.

        Returns the briefing markdown on success, or ``None`` when there is
        nothing new to distill or the Pi turn fails (fail-soft — no partial
        summary is written, and the cursor does not move).
        """
        me = engine_handle or self._handle
        managed = self._manager.get(room)

        if settings.SYNTHESIZER_SOURCE == "memory":
            entries = _read_room_memory(room)
            if not entries:
                logger.info("synthesizer: room %s has no memory to summarize", room)
                await self._say_if_live(
                    managed, room, me, "No memories to summarize yet — post some context first."
                )
                return None
            prompt = _build_prompt(room, entries, directive)
            cursor: dict[str, str] | None = None
            read = len(entries)
        else:
            messages, total = _read_new_messages(room, me=me, full=full)
            if not messages:
                note = (
                    "Nothing new to distill — the standing briefing already covers the room."
                    if total
                    else "No conversation to distill yet — talk in the room first."
                )
                logger.info("synthesizer: nothing new to distill in room %s", room)
                await self._say_if_live(managed, room, me, note)
                return None
            prompt = _build_message_prompt(room, messages, _prior_summary(room), directive)
            last = messages[-1]
            cursor = {"message_id": str(last.id), "recorded_at": last.created_at.isoformat()}
            read = len(messages)

        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_pi_complete, prompt, self._timeout_s),
                timeout=self._timeout_s + 5.0,
            )
        except Exception:
            logger.exception("synthesizer: Pi turn failed for room %s", room)
            await self._say_if_live(managed, room, me, "Pi turn timed out or errored — try again.")
            return None

        response = _strip_fences(raw or "")
        if not response.strip():
            logger.warning("synthesizer: Pi returned empty response for room %s", room)
            await self._say_if_live(managed, room, me, "Pi returned an empty response — try again.")
            return None

        await self._write_summary(room, response, me, cursor)
        logger.info(
            "synthesizer: wrote %s for room %s (%d %s)",
            SYNTHESIS_KEY,
            room,
            read,
            "memories" if cursor is None else "messages",
        )
        await self._say_if_live(managed, room, me, response)
        return response

    async def _say_if_live(
        self, managed: ManagedRoomChannel | None, room: str, sender: str, text: str
    ) -> None:
        if managed is not None:
            await self._say(managed, room, sender, text)

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

    async def _write_summary(
        self, room: str, summary: str, created_by: str, cursor: dict[str, str] | None
    ) -> None:
        """Upsert the summary through the canonical versioned + indexed path.

        The cursor rides along as unmanaged frontmatter, so the position and the
        text it describes land in the same write.
        """
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
                        meta={CURSOR_META_KEY: cursor} if cursor else None,
                    )
                ]
            ),
        )
