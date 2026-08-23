# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Lift a room's old ``plan/tasks.md`` checklist into ``work/`` rows.

``plan/`` used to be a privileged namespace: a shared checklist the compiler
wrote and the board special-cased. It is an ordinary memory namespace now, so a
room that still has a checklist has work recorded somewhere nothing reads.

This runs once per room at startup and is idempotent — a file it has already
lifted carries ``migrated_to_work: true`` and is skipped on every later boot.

**Nothing is deleted.** The prose stays exactly where it is and stays readable
as a memory; only the ``- [ ]`` lines are copied out into rows. A migration that
destroys the thing it converted leaves nobody a way to check the conversion,
and a task list is not ours to throw away.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.filesystem import get_room_dir, list_memory_files, read_memory_file
from app.services.task_compiler import parse_checklist
from app.services.task_sync import ASSIGNEE_FIELD, TASK_KIND, WORK_NAMESPACE, slugify

logger = logging.getLogger(__name__)

PLAN_NAMESPACE = "plan"

#: Frontmatter marking a checklist this has already lifted.
MIGRATED_FLAG = "migrated_to_work"

#: Set on a row this created, so its origin is legible in the file itself.
ORIGIN_FIELD = "migrated_from"


async def migrate_room(room_name: str) -> list[str]:
    """Lift every un-migrated ``plan/`` checklist in one room. Returns new keys."""
    from app.routes.memory import upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    room_dir = get_room_dir(room_name)
    written: list[str] = []
    for key, meta, content in list_memory_files(room_dir, prefix=f"{PLAN_NAMESPACE}/"):
        if meta.get(MIGRATED_FLAG):
            continue
        tasks = parse_checklist(content)
        if not tasks:
            continue
        for task, done in tasks:
            work_key = f"{WORK_NAMESPACE}/{slugify(task.title)}"
            if read_memory_file(room_dir, work_key) is not None:
                continue  # a row already stands for this task; leave it alone
            row_meta: dict[str, Any] = {
                "kind": TASK_KIND,
                "status": "resolved" if done else "open",
                ORIGIN_FIELD: key,
            }
            if task.assignee:
                row_meta[ASSIGNEE_FIELD] = f"@{task.assignee}"
            await upsert_memories(
                room_name,
                MemoryBatchCreate(
                    items=[
                        MemoryCreate(
                            key=work_key,
                            value=task.title,
                            created_by="migration",
                            # The startup scan that runs straight after this
                            # embeds every file it finds changed, so paying for
                            # a model call per lifted task would be paying
                            # twice.
                            embed=False,
                            meta=row_meta,
                        )
                    ]
                ),
                # A room's whole backlog arriving as room traffic on boot would
                # bury whatever the room was actually saying.
                notify=False,
            )
            written.append(work_key)
        await _mark_migrated(room_name, key, meta, content)
        logger.info("migrated %d task(s) out of %s in room %s", len(tasks), key, room_name)
    return written


async def _mark_migrated(room_name: str, key: str, meta: dict, content: str) -> None:
    """Flag the checklist so a later boot skips it, leaving its prose intact."""
    from app.services.fields import upsert_patch

    await upsert_patch(
        room_name, key, meta, content, {MIGRATED_FLAG: True}, "migration", notify=False
    )


async def migrate_all() -> int:
    """Lift every room's checklist. Non-fatal: a bad room never blocks startup."""
    from app.services.filesystem import list_room_names

    total = 0
    for room_name in list_room_names():
        try:
            total += len(await migrate_room(room_name))
        except Exception:
            logger.warning(
                "plan migration failed for room %s (non-fatal)", room_name, exc_info=True
            )
    if total:
        logger.info("plan migration: lifted %d task(s) into work/ rows", total)
    return total
