# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Converged → tasks.

An ``@``-summon makes the aligner score the transcript and emit an L9
``commit:converged`` onto the channel. This module is the *consumer* across that
seam — the backend, seeing the converged verdict, turns it into work the room
can actually pick up.

**The agreement becomes rows.** :mod:`app.services.task_compiler` — one LLM call
— turns the ``assignments`` map into tasks, and each one is written as a
``work/`` memory through the canonical upsert. That makes a task the same kind
of thing as everything else in the room: it carries frontmatter, so it has an
owner, a status and a lease; it is indexed and link-parsed; and the board
projects it as a row an action can move. Fail-soft: a compiler outage falls back to
the raw ``assignments`` so the verdict is never sunk.

Each write announces itself the way every memory write does, so there is no
separate "the plan is ready" broadcast to keep in step with the files.

Deliberately **not** a cognition-engine step: the compiler is a distinct
consumer stage reached across the ``on_converged`` seam, wired in
:mod:`app.main`, never called from inside the aligner. The persister's hook is
``(envelope)`` only, so :class:`~app.services.room_channels.RoomChannelManager`
binds the room via ``_converged_adapter`` before handing it here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.services import l9, task_compiler
from app.services.filesystem import get_room_dir, list_memory_files, read_memory_file
from app.services.tasks import ASSIGNEE_FIELD, TASK_KIND, WORK_NAMESPACE, slugify

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import RoomChannelManager
    from app.services.task_compiler import CompiledTask

logger = logging.getLogger(__name__)


def _assignments_from(envelope: L9) -> dict[str, str]:
    """The ``assignments`` map the aligner put on the converged envelope.

    Coerced to ``{issue: str}`` — a value may be an ``offer`` dict, which the
    compiler renders as an ``issue = value`` line, so a stringified form is
    lossless enough for the prompt and keeps the compiler's typed signature.
    """
    payload = envelope.payload
    data = payload.data if payload is not None and isinstance(payload.data, dict) else {}
    raw = data.get("assignments")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v if isinstance(v, str) else str(v) for k, v in raw.items()}


def open_work(room: str) -> list[tuple[str, str]]:
    """``(key, title)`` for every unfinished ``work/`` row in the room.

    What a re-negotiation is shown, so the model can repeat a task it does not
    mean to change and keep the row it already has.
    """
    rows: list[tuple[str, str]] = []
    for key, meta, content in list_memory_files(get_room_dir(room), prefix=f"{WORK_NAMESPACE}/"):
        if str(meta.get("status") or "open") in ("resolved", "dismissed"):
            continue
        title = next((ln.strip() for ln in content.splitlines() if ln.strip()), key)
        rows.append((key, title.lstrip("# ").strip()))
    return rows


def open_work_markdown(room: str) -> str | None:
    """The room's open work as the checklist the compiler's prompt expects."""
    rows = open_work(room)
    if not rows:
        return None
    return "\n".join(f"- [ ] {title}" for _key, title in rows)


class TaskSyncEngine:
    """Wires ``on_converged`` to task compilation (one per process).

    Dormant like the aligner: nothing runs until a ``commit:converged`` flows
    past the persister, at which point :meth:`handle_converged` schedules one
    compile run per room. A second converged verdict while a run is in flight
    for the same room is ignored (a re-negotiation lands as its own later
    verdict).
    """

    def __init__(self, manager: RoomChannelManager) -> None:
        self._manager = manager
        self._active: set[str] = set()
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- the on_converged seam (sync; room-bound by the manager's adapter) --

    def handle_converged(self, room: str, envelope: L9) -> None:
        """Schedule the compile run for a room's converged verdict."""
        if room in self._active:
            logger.debug("task-sync already active on room %s; ignoring re-converge", room)
            return
        self._active.add(room)
        task = asyncio.create_task(self._run_and_release(room, envelope))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(self, room: str, envelope: L9) -> None:
        try:
            await self.compile_and_write(room, envelope)
        except Exception:
            logger.exception("task-sync run failed on room %s", room)
        finally:
            self._active.discard(room)

    # -- the run --

    async def compile_and_write(self, room: str, envelope: L9) -> list[str]:
        """Compile the verdict into ``work/`` rows and return the keys written."""
        assignments = _assignments_from(envelope)
        tasks = await self._compile(room, assignments)
        written = [await self._write_task(room, t) for t in tasks]
        logger.info("compiled %d task row(s) for room %s", len(written), room)
        return written

    async def _compile(self, room: str, assignments: dict[str, str]) -> list[CompiledTask]:
        """Compile the tasks, falling back to the raw agreement on failure."""
        # The real participant handles, so the compiler tags tasks with the
        # agents that actually negotiated instead of inventing generic ones
        # (@ProductManager, @EngineeringLead, …) — non-actionable work.
        participants = self._manager.members(room)
        try:
            return await task_compiler.compile_tasks(
                room_name=room,
                assignments=assignments,
                joined_intents="",
                issue_options=None,
                open_work=open_work_markdown(room),
                participants=participants,
            )
        except Exception:
            logger.warning(
                "task compiler failed for room %s; writing the raw agreement (fail-soft)", room
            )
            return task_compiler.fallback_tasks(assignments)

    async def _write_task(self, room: str, task: CompiledTask) -> str:
        """Put one task in the room as a ``work/`` row, with its own thread.

        An unchanged task re-compiles to the same key, so this is an upsert onto
        the row it already has. Its ``status`` is deliberately left alone on a
        rewrite: a re-negotiation that restates a task nobody has touched must
        not re-open one somebody already moved.

        A task's thread is **its own**, minted on creation like any board row,
        not the negotiation's — two tasks compiled from one verdict are two
        tasks with two threads, not two rows sharing the conversation that
        produced them. The upsert mints it on the first write; the binding is
        write-once, so a later verdict never moves the row off its thread.
        """
        from app.routes.memory import upsert_memories
        from app.schemas import MemoryBatchCreate, MemoryCreate

        key = f"{WORK_NAMESPACE}/{slugify(task.title)}"
        existing = read_memory_file(get_room_dir(room), key)
        meta: dict[str, Any] = {"kind": TASK_KIND}
        if task.assignee:
            meta[ASSIGNEE_FIELD] = f"@{task.assignee}"
        if existing is None:
            meta["status"] = "open"

        await upsert_memories(
            room,
            MemoryBatchCreate(
                items=[
                    MemoryCreate(
                        key=key,
                        value=task.title,
                        created_by=l9.SYSTEM_ACTOR_ID,
                        meta=meta,
                    )
                ]
            ),
        )
        return key
