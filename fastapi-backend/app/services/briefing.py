# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a room tells an agent when it arrives.

A compact briefing: the room's title, and the work that is open in it. Read on
every dispatch, so it stays a filesystem read with no round trip.

It is assembled from the same rows the board draws, because those are what the
room actually has. There is no separate document to keep in step: a task the
briefing names is a ``work/`` memory somebody can claim, resolve or hand back,
and it says who it is meant for and who is holding it right now — two different
questions a shared checklist could only answer as one.
"""

from __future__ import annotations

from app.services.filesystem import read_room_meta
from app.services.leases import state_of
from app.services.task_sync import ASSIGNEE_FIELD, WORK_NAMESPACE

#: How many open rows a briefing names before it stops. A briefing long enough
#: to skim past is one an agent reads none of.
DEFAULT_LIMIT = 20


def _title(room_name: str) -> str | None:
    meta = read_room_meta(room_name)
    return (meta or {}).get("title")


def open_tasks(room_name: str, *, limit: int = DEFAULT_LIMIT, now=None) -> list[str]:
    """One readable line per open ``work/`` row, held-ness included.

    A row somebody is holding still appears: an agent deciding what to pick up
    needs to see that it is taken, not have it hidden.
    """
    from datetime import UTC, datetime

    from app.services.filesystem import get_room_dir, list_memory_files

    stamp = now or datetime.now(UTC)
    lines: list[str] = []
    for key, meta, content in list_memory_files(
        get_room_dir(room_name), prefix=f"{WORK_NAMESPACE}/"
    ):
        if str(meta.get("status") or "open") in ("resolved", "dismissed"):
            continue
        title = next((ln.strip() for ln in content.splitlines() if ln.strip()), key)
        marks = []
        assignee = meta.get(ASSIGNEE_FIELD)
        if assignee:
            marks.append(f"for {assignee}")
        if state_of(meta, stamp) == "held" and meta.get("owner"):
            marks.append(f"held by {meta['owner']}")
        suffix = f"  ({', '.join(marks)})" if marks else ""
        lines.append(f"- [{key}] {title.lstrip('# ').strip()}{suffix}")
        if len(lines) >= limit:
            break
    return lines


def agent_context(room_name: str, *, limit: int = DEFAULT_LIMIT) -> str | None:
    """The room's briefing, or ``None`` when it has nothing to say yet."""
    parts: list[str] = []
    title = _title(room_name)
    if title:
        parts.append(f"Room: {title}")
    tasks = open_tasks(room_name, limit=limit)
    if tasks:
        parts.append(f"Open work ({len(tasks)}):\n" + "\n".join(tasks))
    elif title:
        parts.append("No open work.")
    return "\n\n".join(parts) if parts else None
