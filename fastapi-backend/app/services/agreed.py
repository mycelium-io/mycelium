# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a team agreed inside a task, saved to the room's memory and carried on.

Two conductor results outlive their run: the **shared summary** a flow that
locks assembles (``accord``'s), and the **decision** a ``concord`` converges
on. Each is saved as one memory per task, under ``context/`` (never a board
namespace, so it is not a row and opens no thread), related to the task with
``relates-to``. A second run in the same task updates the same memory, so its
version counts the times the team went over it.

Everything that works the task afterwards is pointed at them: a later flow's
prompts (``{agreed}``), the digest a woken agent reads, and the turn prompts
of personas and workers in the task's thread. A child row reads its nearest
ancestor's when it has none of its own.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.filesystem import get_room_dir, read_memory_file, room_exists

logger = logging.getLogger(__name__)

#: Where each result is kept, by task.
SUMMARY_PREFIX = "context/summary/"
DECISION_PREFIX = "context/decision/"

#: The frontmatter key a structured result is carried under.
CONTRACT_META = "contract"
DECISION_META = "decision"

#: How far up the ``part-of`` chain a child row looks for its parent's.
ANCESTORS = 4

#: How much of a saved result a prompt carries.
PROMPT_CHARS = 1800


def _slug(task: str) -> str:
    """The part of a task's key a result is filed by: ``work/x`` → ``x``."""
    return task.removeprefix("work/").strip("/")


def summary_key(task: str) -> str:
    return f"{SUMMARY_PREFIX}{_slug(task)}"


def decision_key(task: str) -> str:
    return f"{DECISION_PREFIX}{_slug(task)}"


async def save(
    room: str,
    key: str,
    *,
    body: str,
    meta: dict[str, Any],
    task: str,
    by: str,
    tags: list[str],
) -> bool:
    """Upsert one result through the canonical memory write; ``False`` on failure.

    Never raises: a run's outcome stands whether or not its result could be
    saved, and the caller says which.
    """
    from app.routes.memory import upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    if task:
        meta = {**meta, "relates-to": task}
    try:
        await upsert_memories(
            room,
            MemoryBatchCreate(
                items=[
                    MemoryCreate(
                        key=key,
                        value=body.rstrip("\n") + "\n",
                        created_by=by,
                        embed=True,
                        tags=tags,
                        meta=meta,
                    )
                ]
            ),
        )
    except Exception:
        logger.exception("room %s: could not save %s", room, key)
        return False
    return True


def _parent(room: str, key: str) -> str | None:
    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        return None
    parent = found[0].get("part-of")
    return parent if isinstance(parent, str) and parent else None


def found_for(room: str, task: str) -> list[tuple[str, dict[str, Any], str]]:
    """``(key, frontmatter, body)`` of the results saved for ``task``, or for its
    nearest ancestor that has any. Empty when there are none."""
    if not task or not room_exists(room):
        return []
    room_dir = get_room_dir(room)
    seen: set[str] = set()
    at: str | None = task
    for _ in range(ANCESTORS + 1):
        if at is None or at in seen:
            break
        seen.add(at)
        hits = []
        for key in (summary_key(at), decision_key(at)):
            found = read_memory_file(room_dir, key)
            if found is not None:
                hits.append((key, found[0], found[1]))
        if hits:
            return hits
        at = _parent(room, at)
    return []


def for_prompt(room: str, task: str) -> str:
    """What a later flow's prompt says the team agreed, or ``""`` when nothing was."""
    from app.services.wake_digest import cut

    try:
        hits = found_for(room, task)
    except Exception:
        logger.warning("room %s: could not read what was agreed for %s", room, task)
        return ""
    if not hits:
        return ""
    blocks = [f"From {key}:\n{cut(body, PROMPT_CHARS)}" for key, _meta, body in hits]
    return "What the team already agreed for this task:\n\n" + "\n\n".join(blocks) + "\n\n"


def open_items(meta: dict[str, Any]) -> list[str]:
    """The flagged items a saved shared summary lists, in plain words."""
    made = meta.get(CONTRACT_META)
    if not isinstance(made, dict):
        return []
    return [str(f.get("text")) for f in made.get("flags") or [] if isinstance(f, dict)]


def pointer(room: str, task: str) -> list[str]:
    """Short lines telling someone working the task where its agreements are."""
    try:
        hits = found_for(room, task)
    except Exception:
        return []
    lines = []
    for key, meta, _body in hits:
        what = "shared summary" if key.startswith(SUMMARY_PREFIX) else "decision"
        line = f"{key} ({what}); read it: mycelium memory get {key} --room {room}"
        items = open_items(meta)
        if items:
            shown = "; ".join(items[:3])
            more = f" and {len(items) - 3} more" if len(items) > 3 else ""
            line += f". Open items: {shown}{more}"
        lines.append(line)
    return lines
