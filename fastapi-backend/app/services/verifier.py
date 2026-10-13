# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The verifier: checks what agents say about approvals and merges against the
room's records, and adds a quiet line under a message when a claim doesn't hold.

It never blocks a write and never wakes anyone. In a room that added it (an
engine of kind ``verifier``), every message an agent posts goes through three
steps, each running only on what the one before passed:

1. **Spot claims, locally** (:mod:`app.services.verifier_claims`): a small
   classifier over the hub's search embeddings marks the sentences that claim an
   approval, a completion, a decision or a pull request's state.
2. **Check them against the room's records** (:mod:`app.services.verifier_records`):
   was #N approved by someone else in this room; had #N already merged.
3. **Ask the hub's model** (through Pi) about what's left, with the thread in
   front of it, to dismiss a flag the records got wrong (an approval given in
   words the records miss, a quote of someone else) and to keep the rest.

A kept flag is stored beside the room (:data:`FLAGS_FILE`) and raised as a
``check`` notice, which wakes nobody: the app draws it as a line under the
message, and the agent reads it as the ``Check:`` line of its next wake.
Someone answering *It's fine* raises the same notice with ``state: fine``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.services import verifier_claims, verifier_records
from app.services.persister import (
    TranscriptRecord,
    load_transcript,
    parse_recorded_at,
    read_id,
)

logger = logging.getLogger(__name__)

KIND = "verifier"
FLAGS_FILE = ".verifier-flags.json"
QUOTE_SEP = "\u001f"
THREAD_CONTEXT = 12
CONTEXT_CHARS = 600
PROSE_TYPES = frozenset({"message", "reply"})


# ── Who it reads ─────────────────────────────────────────────────────────────


def verifier_handles(room: str) -> list[str]:
    """The verifier engines this room has added (usually one, or none)."""
    from app.services.room_channels import _registered_agent_handles, _registered_kind

    return [h for h in _registered_agent_handles(room) if _registered_kind(room, h) == KIND]


def _is_agent(room: str, handle: str) -> bool:
    """A registered agent that isn't an engine: the members whose claims it checks."""
    from app.services.room_channels import _is_engine, _is_own_registered_agent

    return _is_own_registered_agent(room, handle) and not _is_engine(room, handle)


# ── The flag store ───────────────────────────────────────────────────────────


def _flags_path(room: str) -> Path:
    from app.services.filesystem import get_room_dir

    return get_room_dir(room) / FLAGS_FILE


def load_flags(room: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(_flags_path(room).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return raw if isinstance(raw, list) else []


def _save_flags(room: str, flags: list[dict[str, Any]]) -> None:
    path = _flags_path(room)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(flags, indent=2), encoding="utf-8")
    tmp.replace(path)


def flags_since(room: str, since: datetime | None = None) -> list[dict[str, Any]]:
    """The room's flags, oldest first, from ``since`` on."""
    flags = load_flags(room)
    if since is None:
        return flags
    return [f for f in flags if (parse_recorded_at(f["at"]) or since) >= since]


# ── Step 3: the hub's model reads the thread ────────────────────────────────

_CONFIRM_PROMPT = """You check one thing an AI agent said in a team chat against the team's records.

The records step thinks this claim doesn't hold up:
- Claim: {sentence}
- Records: {line}
- What was checked: {checked}

The thread up to and including the message (oldest first):
{context}

Decide whether to show a short note under the message. Show it when the claim really isn't backed by anything in this thread or the records. Don't show it when the thread shows the claim is fine: for example the approval was given in words the records missed, the agent is quoting or asking someone else, it's a plan rather than a claim ("once it's approved I'll merge"), or it says plainly what isn't confirmed.

Answer with one JSON object and nothing else:
{{"show": true or false, "quote": "<the exact words in the message that make the claim, copied verbatim>", "why": "<one short sentence>"}}"""


def _context(records: list[TranscriptRecord], record: TranscriptRecord) -> str:
    episode = verifier_records.episode_of(record)
    lines = []
    for r in records:
        if verifier_records.episode_of(r) != episode:
            continue
        payload = (r.content.get("l9") or {}).get("payload") or {}
        if payload.get("type") not in PROSE_TYPES:
            continue
        text = str(r.content.get("content") or "")
        lines.append(f"@{r.sender} ({r.recorded_at[11:16]}): {text[:CONTEXT_CHARS]}")
        if r.message_id == record.message_id:
            break
    return "\n".join(lines[-THREAD_CONTEXT:])


def _ask_model(prompt: str, room: str) -> str:
    """One blocking Pi turn on a throwaway session. Isolated so tests patch it."""
    from app.services.pi_session import PiSession

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session = PiSession(
        session_path=session_dir / f"verifier-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=settings.VERIFIER_PI_TIMEOUT_S,
        openshell=settings.ALIGNER_PI_OPENSHELL,
        operation="verifier",
        room=room,
    )
    return session(prompt)


def _verdict(answer: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", answer, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) and "show" in data else None


# ── The engine ───────────────────────────────────────────────────────────────


class VerifierEngine:
    """Runs the three steps on agent messages in rooms that added the verifier."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._model: verifier_claims.ClaimModel | None = None
        self._model_loaded = False
        from app.services.verifier_learn import Learning

        self.learning = Learning()

    def model(self) -> verifier_claims.ClaimModel | None:
        """The claim spotter for the hub's search model. Blocking: when the search
        model changed and nothing matches it, it is fitted again from the saved
        labels (an embedding pass, no model calls), so call it off the loop."""
        if not self._model_loaded:
            self._model = verifier_claims.load(Path(settings.MYCELIUM_DATA_DIR))
            if self._model is None:
                from app.services import verifier_learn

                self._model = verifier_learn.train()
            self._model_loaded = True
        return self._model

    def reload_model(self) -> None:
        """Pick up a model Learn just wrote."""
        self._model_loaded = False

    # ── Learn ────────────────────────────────────────────────────────────────

    def rooms(self) -> list[str]:
        """Every room on the hub that has added the verifier."""
        from app.services.filesystem import list_room_names

        return sorted(r for r in list_room_names() if verifier_handles(r))

    def start_learn(self) -> bool:
        """Label the rooms' past messages and fit a model to them, in the background.
        False when a run is already going."""
        from app.services import verifier_learn

        if self.learning.state == "running":
            return False
        rooms = self.rooms()
        self.learning = verifier_learn.Learning(
            state="running", started_at=datetime.now(UTC).isoformat(), rooms=rooms
        )
        task = asyncio.get_running_loop().create_task(self._learn(rooms))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _learn(self, rooms: list[str]) -> None:
        from app.services import verifier_learn

        progress = self.learning
        try:
            await verifier_learn.label(rooms, progress)
            model = await asyncio.to_thread(verifier_learn.train)
            if model is not None:
                self.reload_model()
            progress.state = "done"
        except Exception as exc:
            logger.exception("verifier: learning failed")
            progress.state = "failed"
            progress.error = str(exc)
        progress.finished_at = datetime.now(UTC).isoformat()

    def settings_view(self) -> dict[str, Any]:
        """What the hub's Verifier settings section shows."""
        from app.services import embedding, verifier_learn

        model = self.model()
        rooms = self.rooms()
        trained_at = None
        if model is not None and model.source == "learned":
            path = verifier_claims.learned_path(
                Path(settings.MYCELIUM_DATA_DIR), model.embedding_model
            )
            try:
                trained_at = json.loads(path.read_text(encoding="utf-8")).get("trained_at")
            except (OSError, ValueError):
                trained_at = None
        return {
            "enabled": settings.VERIFIER_ENABLED,
            "rooms": rooms,
            "model": embedding.model_name(),
            "using": model.source if model is not None else "none",
            "learned": model.trained_on.get("messages")
            if model is not None and model.source == "learned"
            else None,
            "answers_since_learned": verifier_learn.answers_since(trained_at),
            "estimate": verifier_learn.estimate(rooms),
            "learning": self.learning.view(),
        }

    def handle_recorded(self, room: str, record: TranscriptRecord) -> None:
        """The persister's hook, for every recorded message: check agent prose."""
        if not settings.VERIFIER_ENABLED:
            return
        payload = (record.content.get("l9") or {}).get("payload") or {}
        if payload.get("type") not in PROSE_TYPES:
            return
        if not str(record.content.get("content") or "").strip():
            return
        try:
            if not verifier_handles(room) or not _is_agent(room, record.sender):
                return
        except Exception:
            logger.exception("verifier: membership check failed in %s", room)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._serial(room, record))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _serial(self, room: str, record: TranscriptRecord) -> None:
        lock = self._locks.setdefault(room, asyncio.Lock())
        async with lock:
            try:
                await self.check_message(room, record)
            except Exception:
                logger.exception("verifier: check failed for %s in %s", record.message_id, room)

    async def check_message(self, room: str, record: TranscriptRecord) -> list[dict[str, Any]]:
        """The three steps for one message. Returns the flags it raised."""
        model = await asyncio.to_thread(self.model)
        if model is None:
            return []
        text = str(record.content.get("content") or "")
        claims = await asyncio.to_thread(verifier_claims.spot, model, text)
        if not claims:
            return []
        at = parse_recorded_at(record.recorded_at) or datetime.now(UTC)
        records = await asyncio.to_thread(load_transcript, room)
        thread = verifier_records.episode_of(record)
        findings: list[verifier_records.Finding] = []
        for claim in claims:
            findings += verifier_records.check(
                claim.sentence,
                claim.kinds,
                speaker=record.sender,
                at=at,
                thread=thread,
                records=records,
            )
        raised = []
        message_id = str(read_id(record))
        seen = {(f["message_id"], f["ref"], f["claim"]) for f in load_flags(room)}
        for finding in findings:
            if (message_id, finding.ref, finding.claim) in seen:
                continue
            quotes = list(finding.quotes)
            why = ""
            if settings.VERIFIER_CONFIRM:
                prompt = _CONFIRM_PROMPT.format(
                    sentence=finding.sentence,
                    line=finding.line,
                    checked="; ".join(f"{c['what']}: {c['found']}" for c in finding.checked),
                    context=_context(records, record),
                )
                try:
                    verdict = _verdict(await asyncio.to_thread(_ask_model, prompt, room))
                except Exception:
                    logger.exception("verifier: the model step failed in %s", room)
                    verdict = None
                if verdict is None or not verdict.get("show"):
                    continue
                quote = str(verdict.get("quote") or "").strip()
                if quote and quote in text:
                    quotes = [quote]
                why = str(verdict.get("why") or "")
            raised.append(await self._raise(room, record, finding, quotes, why))
            seen.add((message_id, finding.ref, finding.claim))
        return raised

    async def _raise(
        self,
        room: str,
        record: TranscriptRecord,
        finding: verifier_records.Finding,
        quotes: list[str],
        why: str,
    ) -> dict[str, Any]:
        thread = verifier_records.episode_of(record)
        flag = {
            "flag_id": uuid.uuid4().hex[:12],
            # The history read's id, so the line finds its message in the app and CLI.
            "message_id": str(read_id(record)),
            "key": (thread or "").rsplit(":", 1)[-1] or "live",
            "about": record.sender,
            "by": verifier_handles(room)[0] if verifier_handles(room) else KIND,
            "claim": finding.claim,
            "ref": finding.ref,
            "line": finding.line,
            "sure": finding.sure,
            "quotes": quotes,
            "sentence": finding.sentence,
            "why": why,
            "checked": finding.checked,
            "state": "shown",
            "fine_by": None,
            "at": datetime.now(UTC).isoformat(),
        }
        flags = load_flags(room)
        flags.append(flag)
        _save_flags(room, flags)
        await self._notice(room, flag)
        return flag

    async def _notice(self, room: str, flag: dict[str, Any]) -> None:
        await self._manager.raise_notice(
            room,
            subkind="check",
            key=flag["key"],
            by=flag["by"],
            message_id=flag["message_id"],
            flag_id=flag["flag_id"],
            about=flag["about"],
            line=flag["line"],
            sure="true" if flag["sure"] else "false",
            quotes=QUOTE_SEP.join(flag["quotes"]),
            ref=flag["ref"],
            state=flag["state"],
            fine_by=flag.get("fine_by"),
        )

    async def mark_fine(self, room: str, flag_id: str, by: str) -> dict[str, Any] | None:
        """Someone says a flag is fine: hide it for everyone and keep the answer."""
        lock = self._locks.setdefault(room, asyncio.Lock())
        async with lock:
            flags = load_flags(room)
            flag = next((f for f in flags if f["flag_id"] == flag_id), None)
            if flag is None:
                return None
            if flag["state"] != "fine":
                flag["state"] = "fine"
                flag["fine_by"] = by
                flag["fine_at"] = datetime.now(UTC).isoformat()
                _save_flags(room, flags)
                from app.services import verifier_learn

                await asyncio.to_thread(verifier_learn.record_answer, room, flag)
                await self._notice(room, flag)
            return flag


def check_lines(room: str, handle: str, since: list[Any]) -> list[str]:
    """The wake digest's ``Check:`` lines: flags about ``handle`` raised since its
    last turn and still shown. ``since`` is the records the digest is summarising."""
    raised = set()
    for record in since:
        payload = (record.content.get("l9") or {}).get("payload") or {}
        data = payload.get("data") or {}
        if (
            payload.get("type") == "notice"
            and data.get("subkind") == "check"
            and data.get("about") == handle
        ):
            raised.add(data.get("flag_id"))
    if not raised:
        return []
    lines = []
    for flag in load_flags(room):
        if flag["flag_id"] in raised and flag["state"] == "shown":
            # "#1266 was already merged, at 20:08." reads on its own; "Can't find an
            # approval for #1278." needs a subject once it follows "but".
            line = (
                flag["line"]
                if flag["sure"]
                else f"the verifier {flag['line'][0].lower()}{flag['line'][1:]}"
            )
            lines.append(
                f'You said "{flag["sentence"]}", but {line} Fix it in the room, or say where it came from.'
            )
    return lines
