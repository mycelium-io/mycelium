# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Converged → plan → memory sync.

An ``@``-summon makes the aligner score the transcript and emit an L9
``commit:converged`` onto the channel. This module is the *consumer* across that
seam — the backend, seeing the converged verdict, turns it into work:

1. **Compile the plan.** The converged envelope carries ``assignments`` (built by
   the aligner in ``aligner._fold``). :mod:`app.services.plan_compiler` — one LLM
   call — turns that into a ``- [ ]`` checklist materialized at ``plan/tasks.md``.
   Fail-soft: a compiler outage falls back to the raw ``assignments`` so the
   verdict is never sunk.

2. **Sync it as memory.** The compiled plan becomes a ``knowledge`` message that
   **carries the content** (push-with-content) so every participant's
   local store converges — and, because the verdict is already on the wire when
   this fires, the ``knowledge`` broadcast doubles as the **"plan ready" signal**
   a consumer waits for.

Deliberately **not** a cognition-engine step (the CLAUDE.md plan-compiler
decision): the compiler is a distinct consumer stage reached across the
``on_converged`` seam, wired in :mod:`app.main`, never called from inside the
aligner. The persister's hook is ``(envelope)`` only, so
:class:`~app.services.room_channels.RoomChannelManager`
binds the room via ``_converged_adapter`` before handing it here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.services import l9, memory_sync, plan, plan_compiler
from app.services.l9_slim import serialize_content

if TYPE_CHECKING:
    from app.services.l9_models import L9
    from app.services.room_channels import RoomChannelManager

logger = logging.getLogger(__name__)

PLAN_TASKS_KEY = f"{plan.PLAN_DIR}/{plan.DEFAULT_TASK_FILE}"


def _assignments_from(envelope: L9) -> dict[str, str]:
    """The ``assignments`` map the aligner put on the converged envelope.

    Coerced to ``{handle: str}`` — a value may be an ``offer`` dict, which the
    compiler renders as an ``issue = value`` line, so a stringified form is
    lossless enough for the prompt and keeps the compiler's typed signature.
    """
    payload = envelope.payload
    data = payload.data if payload is not None and isinstance(payload.data, dict) else {}
    raw = data.get("assignments")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v if isinstance(v, str) else str(v) for k, v in raw.items()}


class PlanSyncEngine:
    """Wires ``on_converged`` to plan compilation + memory sync (one per process).

    Dormant like the aligner: nothing runs until a ``commit:converged`` flows past
    the persister, at which point :meth:`handle_converged` schedules one compile +
    sync run per room. A second converged verdict while a run is in flight for the
    same room is ignored (a run re-negotiation lands as its own later verdict).
    """

    def __init__(self, manager: RoomChannelManager) -> None:
        self._manager = manager
        self._active: set[str] = set()
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- the on_converged seam (sync; room-bound by the manager's adapter) --

    def handle_converged(self, room: str, envelope: L9) -> None:
        """Schedule the compile + sync run for a room's converged verdict."""
        if room in self._active:
            logger.debug("plan-sync already active on room %s; ignoring re-converge", room)
            return
        self._active.add(room)
        task = asyncio.create_task(self._run_and_release(room, envelope))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_release(self, room: str, envelope: L9) -> None:
        try:
            await self.compile_and_sync(room, envelope)
        except Exception:
            logger.exception("plan-sync run failed on room %s", room)
        finally:
            self._active.discard(room)

    # -- the run --

    async def compile_and_sync(self, room: str, envelope: L9) -> memory_sync.KnowledgeWrite | None:
        """Compile ``plan/tasks.md`` from the verdict and broadcast it as memory.

        Returns the :class:`~app.services.memory_sync.KnowledgeWrite` broadcast,
        or ``None`` when there was no channel/assignments to act on.
        """
        assignments = _assignments_from(envelope)
        existing_plan = plan.read_plan_file(room)
        base_version = _current_plan_version(room)
        new_version = (base_version or 0) + 1

        body = await self._compile_body(room, assignments, existing_plan)
        plan.write_plan_file(room, body, updated_by=l9.SYSTEM_ACTOR_ID, version=new_version)
        plan.set_title_from_body_if_absent(room, body, updated_by=l9.SYSTEM_ACTOR_ID)
        logger.info("compiled plan/tasks.md for room %s (v%d)", room, new_version)

        return await self._broadcast_knowledge(room, body, new_version, base_version)

    async def _compile_body(
        self, room: str, assignments: dict[str, str], existing_plan: str | None
    ) -> str:
        """Compile the plan body, falling back to the raw agreement on failure."""
        # The real participant handles, so the compiler tags tasks with the agents
        # that actually negotiated instead of inventing generic ones
        # (@ProductManager, @EngineeringLead, …) — a non-actionable plan.
        participants = self._manager.members(room)
        try:
            return await plan_compiler.compile_plan(
                room_name=room,
                assignments=assignments,
                joined_intents="",
                issue_options=None,
                existing_plan=existing_plan,
                participants=participants,
            )
        except Exception:
            logger.warning(
                "plan compiler failed for room %s; writing raw agreement (fail-soft)", room
            )
            return plan_compiler.fallback_body(assignments)

    async def _broadcast_knowledge(
        self, room: str, body: str, version: int, base_version: int | None
    ) -> memory_sync.KnowledgeWrite | None:
        """Emit the compiled plan as a ``knowledge`` message carrying its content."""
        managed = self._manager.get(room)
        if managed is None:
            logger.debug("no live channel for room %s; plan written but not synced", room)
            return None
        write = memory_sync.KnowledgeWrite(
            key=PLAN_TASKS_KEY,
            content=body.rstrip("\n") + "\n",
            version=version,
            created_by=l9.SYSTEM_ACTOR_ID,
            updated_by=l9.SYSTEM_ACTOR_ID,
            updated_at=_now_iso(),
            base_version=base_version,
        )
        envelope = memory_sync.build_knowledge_envelope(
            room=room, write=write, recipients=self._manager.members(room)
        )
        content = serialize_content(envelope, extra={"content": f"plan updated → {PLAN_TASKS_KEY}"})
        try:
            await managed.channel.send(envelope, extra={"content": content["content"]})
        except Exception:
            logger.warning("failed to broadcast plan knowledge on room %s", room)
        # Record locally (deduped by message id) so the transcript + UI bus see
        # the "plan ready" signal even if SLIM never loops our broadcast back.
        if managed.persister is not None:
            managed.persister.ingest_local(envelope, content)
        return write


def _current_plan_version(room: str) -> int | None:
    """The version of the room's current ``plan/tasks.md`` frontmatter, if any."""
    from app.services.filesystem import get_room_dir, read_memory_file

    result = read_memory_file(get_room_dir(room), PLAN_TASKS_KEY)
    if result is None:
        return None
    try:
        return int(result[0].get("version", 1))
    except (TypeError, ValueError):
        return 1


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
