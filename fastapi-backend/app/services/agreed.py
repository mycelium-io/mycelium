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

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.services.filesystem import get_room_dir, read_memory_file, room_exists

if TYPE_CHECKING:
    from app.services.persister import TranscriptRecord

logger = logging.getLogger(__name__)

#: Where each result is kept, by task.
SUMMARY_PREFIX = "context/summary/"
DECISION_PREFIX = "context/decision/"

#: The frontmatter key a structured result is carried under.
CONTRACT_META = "contract"
DECISION_META = "decision"

#: How far up the ``part-of`` chain a child row looks for its parent's.
ANCESTORS = 4

#: How much of a saved result a prompt carries, and the one line a wake shows.
PROMPT_CHARS = 1800
GIST_CHARS = 400

#: The open item a member adds from the task's thread with a ``conflict:`` line.
REPORTED = "reported_conflict"
#: What later prompts tell members about adding one.
CONFLICT_HINT = (
    "If your work runs into something in the shared summary that doesn't fit, say so "
    "in the task's thread on a line starting `conflict:`; it's added to the summary's "
    "open items.\n\n"
)


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
    base_version: int | None = None,
) -> bool:
    """Upsert one result through the canonical memory write; ``False`` on failure.

    Never raises: a run's outcome stands whether or not its result could be
    saved, and the caller says which. With ``base_version``, the write is
    refused (``False``) when the memory moved on since that version.
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
                        base_version=base_version,
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
    hint = CONFLICT_HINT if any(k.startswith(SUMMARY_PREFIX) for k, _m, _b in hits) else ""
    return "What the team already agreed for this task:\n\n" + "\n\n".join(blocks) + "\n\n" + hint


def open_items(meta: dict[str, Any]) -> list[str]:
    """The flagged items a saved shared summary lists, in plain words."""
    made = meta.get(CONTRACT_META)
    if not isinstance(made, dict):
        return []
    return [str(f.get("text")) for f in made.get("flags") or [] if isinstance(f, dict)]


def _decision_gist(decided: dict[str, Any]) -> str:
    label, text = decided.get("pick"), decided.get("text")
    if not label or not text:
        return ""
    said = f"going with {label}: {text}"
    if decided.get("agreed"):
        return f"{said}; everyone meets the bar"
    short = [
        f"{s.get('member')} ({s.get('why')})" if s.get("why") else str(s.get("member"))
        for s in decided.get("short") or []
        if isinstance(s, dict)
    ]
    return f"{said}; best found, short of the bar for {', '.join(short)}" if short else said


def _summary_gist(made: dict[str, Any]) -> str:
    points = [p for p in made.get("points") or [] if isinstance(p, dict)]
    parts = [str(p.get("text")) for p in points if p.get("type") == "objective"][:2]
    parts += [
        f"{g['term']} means {g['meanings'][0]['text']}"
        for g in made.get("glossary") or []
        if isinstance(g, dict) and g.get("status") == "agreed" and g.get("meanings")
    ][:3]
    parts += [str(p.get("text")) for p in points if p.get("type") == "constraint"][:2]
    return "; ".join(t.rstrip(".") for t in parts if t)


def gist(key: str, meta: dict[str, Any]) -> str:
    """What a saved result says, in one line: the decision and where it stands,
    or a shared summary's objectives, agreed words and constraints."""
    from app.services.wake_digest import cut

    if key.startswith(DECISION_PREFIX):
        decided = meta.get(DECISION_META)
        said = _decision_gist(decided) if isinstance(decided, dict) else ""
    else:
        made = meta.get(CONTRACT_META)
        said = _summary_gist(made) if isinstance(made, dict) else ""
    return cut(said, GIST_CHARS) if said else ""


def pointer(room: str, task: str) -> list[str]:
    """Short lines telling someone working the task what its agreements say,
    and where to read them in full."""
    try:
        hits = found_for(room, task)
    except Exception:
        return []
    lines = []
    for key, meta, _body in hits:
        what = "shared summary" if key.startswith(SUMMARY_PREFIX) else "decision"
        said = gist(key, meta)
        line = f"{key} ({what})" + (f": {said}" if said else "")
        line += f"; read it: mycelium memory get {key} --room {room}"
        items = open_items(meta)
        if items:
            shown = "; ".join(items[:3])
            more = f" and {len(items) - 3} more" if len(items) > 3 else ""
            line += f". Open items: {shown}{more}"
        lines.append(line)
    return lines


#: Payload types a member writes prose in.
_PROSE = frozenset({"message", "reply"})
#: The payload key the conductor's own posts carry their line under; its
#: prompts are not a member reporting anything.
_CONDUCTOR_LINE = "conductor"

#: In-flight writes, held so they aren't collected mid-flight.
_pending: set[asyncio.Task[Any]] = set()


def reported(room: str, record: TranscriptRecord) -> tuple[str, list[str]] | None:
    """``(summary key, conflicts)`` when ``record`` is a member's message in a
    task's thread with ``conflict:`` lines and the task has a shared summary."""
    from app.services import markers, tasks
    from app.services.persister import record_episode

    payload = (record.content.get("l9") or {}).get("payload") or {}
    if payload.get("type") not in _PROSE or _CONDUCTOR_LINE in (payload.get("data") or {}):
        return None
    conflicts = markers.conflict_lines(str(record.content.get("content") or ""))
    episode = record_episode(record)
    if not conflicts or not episode:
        return None
    row = tasks.row_of_episode(room, episode)
    if row is None:
        return None
    summary = next(
        (k for k, _m, _b in found_for(room, row[0]) if k.startswith(SUMMARY_PREFIX)), None
    )
    return (summary, conflicts) if summary else None


#: One lock per (room, summary key), so conflict lines arriving together are
#: added one after another rather than each overwriting the other.
_locks: dict[tuple[str, str], asyncio.Lock] = {}
#: How many times an add is tried when the summary moved under it.
ADD_TRIES = 3


async def add_conflicts(room: str, key: str, by: str, conflicts: list[str]) -> bool:
    """Add what ``by`` reported to the shared summary's open items, once each,
    and save it; ``False`` when there was nothing new or the save failed.

    Only the contract changes: every other key of the summary's frontmatter is
    written back as it was. Adds to one summary run one at a time, and each
    write is checked against the version it read, so a summary rewritten in
    between (an accord run again) is read afresh rather than overwritten."""
    async with _locks.setdefault((room, key), asyncio.Lock()):
        for _ in range(ADD_TRIES):
            saved = await _add_conflicts_once(room, key, by, conflicts)
            if saved is not None:
                return saved
        return False


async def _add_conflicts_once(room: str, key: str, by: str, conflicts: list[str]) -> bool | None:
    """One read, add and checked write: ``None`` when the write was refused."""
    from app.services import frame as framing
    from app.services.filesystem import unmanaged_meta

    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        return False
    meta, _body = found
    made = meta.get(CONTRACT_META)
    if not isinstance(made, dict):
        return False
    flags = list(made.get("flags") or [])
    had = {f.get("text") for f in flags if isinstance(f, dict)}
    new = [
        {"kind": REPORTED, "text": f"{by} says this doesn't fit: {c}", "members": [by]}
        for c in conflicts
    ]
    new = [f for f in new if f["text"] not in had]
    if not new:
        return False
    made = {**made, "flags": flags + new}
    tags = meta.get("tags")
    saved = await save(
        room,
        key,
        body=framing.render(made),
        meta={**unmanaged_meta(meta), CONTRACT_META: made},
        task=str(meta.get("relates-to") or made.get("task") or ""),
        by=by,
        tags=list(tags) if isinstance(tags, list) and tags else ["shared-summary"],
        base_version=meta.get("version") if isinstance(meta.get("version"), int) else None,
    )
    return True if saved else None


def handle_recorded(room: str, record: TranscriptRecord) -> None:
    """The persister's hook, for every recorded message: a ``conflict:`` line in
    a task's thread goes onto its shared summary's open items. A memory write,
    not a message: nobody is woken by it."""
    try:
        found = reported(room, record)
    except Exception:
        logger.exception("room %s: could not read %s for conflicts", room, record.message_id)
        return
    if found is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    key, conflicts = found
    task = loop.create_task(add_conflicts(room, key, record.sender, conflicts))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
