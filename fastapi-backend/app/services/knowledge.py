# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a room's team learned: memories with a kind, a task, and where they came from.

A memory can say what it is (``kind``: a ``fact``, a ``finding`` or a
``dead-end``), the task it was learned in (``task``, a board row's key), and
what it came from (``derived-from``, a typed relation the link index keeps
with backlinks, like ``part-of`` or ``relates-to``). A memory is **open** (``open: true``) while
someone is still working on it, and **settled** once it holds.

Together they are the room's knowledge graph: what the team learned, what each
piece came from, and who wrote it. A task is a lens on it: the memories it
produced, and the ones elsewhere they came from or fed. The fields are
ordinary frontmatter written through the memory route, checked there
(:func:`check`) so a bad ``kind`` or a ``derived-from`` naming nothing is
refused with a stable code, like every other memory write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.board import title_of
from app.services.filesystem import changes_in, list_memory_files, read_memory_file, room_path

if TYPE_CHECKING:
    from pathlib import Path

KIND_FIELD = "kind"
TASK_FIELD = "task"
OPEN_FIELD = "open"
DERIVED_FROM = "derived-from"
RELATES_TO = "relates-to"

#: The kinds a memory can be given.
KINDS = ("fact", "finding", "dead-end")


class Refused(Exception):
    """A write whose knowledge fields the room can't take: a memory-write code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def keys_of(raw: Any) -> list[str]:
    """A relation's value as keys: one key, or a list of them."""
    values = raw if isinstance(raw, list) else [raw]
    return [v.strip() for v in values if isinstance(v, str) and v.strip()]


def kind_of(key: str, meta: dict[str, Any]) -> str | None:
    """What a memory is as knowledge, or ``None`` for one that isn't."""
    kind = meta.get(KIND_FIELD)
    if kind in KINDS and not _is_task_key(key):
        return str(kind)
    return None


def task_of(meta: dict[str, Any]) -> str | None:
    """The task a memory was learned in: its ``task``."""
    task = meta.get(TASK_FIELD)
    if isinstance(task, str) and task.strip():
        return task.strip()
    return None


def _is_task_key(key: str) -> bool:
    from app.services.tasks import BOARD_NAMESPACES

    return key.split("/", 1)[0] in BOARD_NAMESPACES


def _changes(meta: dict[str, Any], old_meta: dict[str, Any], name: str) -> bool:
    return name in meta and meta[name] != old_meta.get(name)


def check(room: str, key: str, meta: dict[str, Any], old_meta: dict[str, Any]) -> dict[str, Any]:
    """Refuse knowledge fields a write can't carry, and return the meta to save.

    A memory without its own ``task`` takes the task of the first memory it's
    derived from, so a finding written from another lands in the same task.
    """
    base = room_path(room)
    if _changes(meta, old_meta, KIND_FIELD):
        kind = meta[KIND_FIELD]
        if _is_task_key(key):
            raise Refused(
                "memory.learned_on_task",
                f"{key} is a task, and a task's kind is its own. Save what you learned "
                "under a key of its own, with --task pointing at the task.",
            )
        if kind not in KINDS:
            raise Refused(
                "memory.learned_kind",
                f"A memory's kind is one of {', '.join(KINDS)}, not {kind!r}.",
            )
    if _changes(meta, old_meta, DERIVED_FROM):
        sources = keys_of(meta[DERIVED_FROM])
        missing = [k for k in sources if k == key or read_memory_file(base, k) is None]
        if missing:
            raise Refused(
                "memory.derived_from_missing",
                f"derived-from names {', '.join(missing)}, which "
                f"{'is' if len(missing) == 1 else 'are'} not a memory in this room. "
                "Point it at the memories this one came from.",
            )
    if _changes(meta, old_meta, TASK_FIELD):
        task = meta[TASK_FIELD]
        if task and (
            not isinstance(task, str)
            or not _is_task_key(task)
            or read_memory_file(base, task) is None
        ):
            raise Refused(
                "memory.task_missing",
                f"task names {task!r}, which isn't a task on this room's board.",
            )
    if _changes(meta, old_meta, OPEN_FIELD) and not isinstance(meta[OPEN_FIELD], bool | None):
        raise Refused("memory.learned_kind", "open is true or false.")
    if not meta.get(TASK_FIELD) and not old_meta.get(TASK_FIELD):
        for source in keys_of(meta.get(DERIVED_FROM)):
            found = read_memory_file(base, source)
            inherited = task_of(found[0]) if found else None
            if inherited:
                return {**meta, TASK_FIELD: inherited}
    return meta


def _node(key: str, meta: dict[str, Any], content: str) -> dict[str, Any]:
    return {
        "key": key,
        "kind": kind_of(key, meta),
        "title": title_of(key, content),
        "by": str(meta.get("created_by") or ""),
        "task": task_of(meta),
        "open": meta.get(OPEN_FIELD) is True,
        "derived_from": keys_of(meta.get(DERIVED_FROM)),
        "relates_to": [k for k in keys_of(meta.get(RELATES_TO)) if not _is_task_key(k)],
        "tags": [str(t) for t in meta.get("tags") or [] if t],
        "updated_at": str(meta.get("updated_at") or meta.get("created_at") or ""),
    }


#: Each room folder's graph with the change count it was built at (``changes_in``).
_graphs: dict[str, tuple[int, dict[str, Any]]] = {}


def room_knowledge(room: str) -> dict[str, Any]:
    """Everything the room's team learned, and the tasks it was learned in.

    Built by reading every memory in the room, so it is kept until a memory
    there is written or deleted. The graph returned is shared: read it, never
    change it (``lens`` copies what it marks). Blocking; call it off the loop.
    """
    base = room_path(room)
    # By folder rather than name: a room's name means another folder under
    # another data dir.
    folder = str(base.resolve())
    seen = changes_in(base)
    kept = _graphs.get(folder)
    if kept is not None and kept[0] == seen:
        return kept[1]
    graph = _build(base)
    _graphs[folder] = (seen, graph)
    return graph


def _build(base: Path) -> dict[str, Any]:
    memories = [
        _node(key, meta, content)
        for key, meta, content in list_memory_files(base, limit=None)
        if kind_of(key, meta)
    ]
    tasks = []
    for task in dict.fromkeys(m["task"] for m in memories if m["task"]):
        found = read_memory_file(base, task)
        tasks.append({"key": task, "title": title_of(task, found[1]) if found else task})
    return {"tasks": tasks, "memories": memories}


def lens(graph: dict[str, Any], task: str) -> dict[str, Any]:
    """The room's knowledge through one task: what it produced, and the
    memories elsewhere those came from or fed into, marked ``in_task``."""
    nodes = {m["key"]: m for m in graph["memories"]}
    own = {k for k, m in nodes.items() if m["task"] == task}
    near = set(own)
    for key in own:
        near.update(k for k in nodes[key]["derived_from"] if k in nodes)
    near.update(k for k, m in nodes.items() if own & set(m["derived_from"]))
    memories = [{**nodes[k], "in_task": k in own} for k in nodes if k in near]
    return {"tasks": [t for t in graph["tasks"] if t["key"] == task], "memories": memories}


async def settle(room: str, key: str, by: str) -> dict[str, Any]:
    """Mark a memory as holding: it's no longer open."""
    from app.services import fields

    found = read_memory_file(room_path(room), key)
    if found is None:
        raise LookupError(key)
    meta, content = found
    if not kind_of(key, meta):
        raise ValueError(f"{key} isn't a fact, finding or dead end, so there's nothing to settle.")
    if meta.get(OPEN_FIELD) is True:
        await fields.upsert_patch(room, key, meta, content, {OPEN_FIELD: None}, by)
        meta = {**meta, OPEN_FIELD: None}
    return _node(key, meta, content)
