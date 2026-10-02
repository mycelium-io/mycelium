# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a pattern's run stands, restated after every step.

A room loaded from a pattern knows its scenario (``.room.json`` ``pattern``),
and a scenario with ``after.track`` says what its result is about. After each
step the conductor takes, and once when the run closes, this reads what has
been said in the task's thread and asks Pi for two lines: where the run stands,
as a headline, and what changed from where it started. It is written to the
room as :data:`STANDING_KEY`, so every viewer reads the same answer, a reload
keeps it, and the write reaches the app like any other memory.

It is one call per step whoever is watching. Calls for a room never overlap: a
step that lands while one is running is folded into a single call after it,
over everything said by then, so the answer is always about the latest step.
A call that fails leaves the previous answer standing.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.services import l9, patterns
from app.services.filesystem import read_room_meta

logger = logging.getLogger(__name__)

STANDING_KEY = "context/standing"

#: How long one restatement may take.
TIMEOUT_S = 60.0

#: How much of each message the prompt carries; a long reply is cut, not dropped.
MESSAGE_CHARS = 1500

#: How many of the latest messages the prompt carries.
MAX_MESSAGES = 30

_OUTCOME_WORDS = {
    "resolved": "It has finished and reached its end.",
    "converged": "It has finished: the members agreed.",
    "rejected": "It has finished without the result it was after.",
}


def scenario_of(room: str) -> patterns.Scenario | None:
    """The scenario a room was loaded from, when it says what its result is about."""
    meta = read_room_meta(room) or {}
    name = meta.get("pattern")
    if not name:
        return None
    try:
        scenario = patterns.read_pack(name).scenario
    except (patterns.PatternNotFound, patterns.PatternInvalid):
        return None
    return scenario if scenario.after is not None else None


def build_prompt(
    scenario: patterns.Scenario, said: list[tuple[str, str]], outcome: str | None
) -> str:
    """What Pi is asked: where it started, what matters, what was said."""
    track = scenario.after.track if scenario.after is not None else ""
    lines = [
        "You are telling someone who is watching a team of agents where their work "
        "stands, in plain English.",
        "",
    ]
    if scenario.before is not None:
        start = scenario.before.headline
        if scenario.before.detail:
            start += f". {scenario.before.detail}"
        lines += [f"It started here: {start}", ""]
    if track:
        lines += [f"What the result is about: {track}", ""]
    lines += [_OUTCOME_WORDS.get(outcome or "", "It is still going."), ""]
    lines.append("What has been said so far, oldest first:")
    for sender, text in said[-MAX_MESSAGES:]:
        cut = text if len(text) <= MESSAGE_CHARS else text[:MESSAGE_CHARS] + " […]"
        lines.append(f"- {sender}: {cut}")
    lines += [
        "",
        "Answer in exactly two lines and nothing else.",
        "Line 1: where it stands now, as a headline of at most 12 words.",
        "Line 2: one or two sentences: what has changed from where it started, and "
        "what is still open. Use the figures the messages use.",
        "Say only what the messages support. No preamble, no labels, no markdown.",
    ]
    return "\n".join(lines)


def parse_answer(text: str) -> tuple[str, str] | None:
    """The headline and the detail, or None for an answer with no headline."""
    lines = [ln.strip().strip("*#").strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    for prefix in ("Line 1:", "Line 2:"):
        lines = [ln.removeprefix(prefix).strip() for ln in lines]
    return lines[0], " ".join(lines[1:])


def _said(room: str, thread: str) -> list[tuple[str, str]]:
    """What the members said in the thread, oldest first, without the conductor."""
    from app.services.persister import prose_messages

    quiet = {settings.CONDUCTOR_HANDLE.lower(), patterns.CONDUCTOR, l9.SYSTEM_ACTOR_ID}
    return [
        (m.sender_handle, m.content)
        for m in prose_messages(room)
        if m.episode == thread and m.sender_handle.lower() not in quiet and m.content.strip()
    ]


def _complete(prompt: str, room: str) -> str:
    """One blocking Pi turn on a throwaway session. Isolated so tests patch it."""
    from app.services.pi_session import PiSession

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session = PiSession(
        session_path=session_dir / f"standing-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=TIMEOUT_S,
        openshell=settings.ALIGNER_PI_OPENSHELL,
        operation="standing",
        room=room,
    )
    return session(prompt)


async def restate(room: str, thread: str, outcome: str | None) -> bool:
    """Write where the run in ``thread`` stands; False when there was nothing to say."""
    scenario = scenario_of(room)
    if scenario is None:
        return False
    said = _said(room, thread)
    if not said:
        return False
    prompt = build_prompt(scenario, said, outcome)
    try:
        answer = await asyncio.wait_for(
            asyncio.to_thread(_complete, prompt, room), timeout=TIMEOUT_S + 5.0
        )
    except Exception:
        logger.warning("standing: no restatement for %s", room, exc_info=True)
        return False
    parsed = parse_answer(answer or "")
    if parsed is None:
        logger.warning("standing: empty restatement for %s", room)
        return False
    headline, detail = parsed

    from app.routes.memory import upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    meta: dict[str, Any] = {
        "headline": headline,
        "detail": detail,
        "state": outcome or "running",
        "thread": thread,
        "said": len(said),
    }
    await upsert_memories(
        room,
        MemoryBatchCreate(
            items=[
                MemoryCreate(
                    key=STANDING_KEY,
                    value=f"{headline}\n\n{detail}".strip(),
                    created_by=l9.SYSTEM_ACTOR_ID,
                    embed=False,
                    meta=meta,
                )
            ]
        ),
    )
    return True


class Standing:
    """Restates a room's run after each step, one call at a time per room."""

    def __init__(self) -> None:
        self._running: dict[str, asyncio.Task[None]] = {}
        #: The latest step a running call has not seen yet, per room.
        self._next: dict[str, tuple[str, str | None]] = {}

    def on_step(self, room: str, thread: str, outcome: str | None) -> None:
        """The conductor's step hook: schedule a restatement and return."""
        if scenario_of(room) is None:
            return
        if room in self._running:
            self._next[room] = (thread, outcome)
            return
        task = asyncio.create_task(self._drain(room, thread, outcome))
        self._running[room] = task

    async def _drain(self, room: str, thread: str, outcome: str | None) -> None:
        try:
            while True:
                try:
                    await restate(room, thread, outcome)
                except Exception:
                    logger.exception("standing: restatement failed in %s", room)
                if room not in self._next:
                    return
                thread, outcome = self._next.pop(room)
        finally:
            self._running.pop(room, None)

    async def idle(self) -> None:
        """Wait until no restatement is running. For tests."""
        while self._running:
            await asyncio.gather(*self._running.values(), return_exceptions=True)
