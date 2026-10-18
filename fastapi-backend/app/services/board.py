# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The board as people read it: the room's epics as paths, and its other tasks.

An **epic** is a task with parts: rows that name it with ``part-of`` (what
``board new --parent`` writes). It is not a new kind of thing, so nothing about
it is stored. Everything here is worked out on read from the rows' frontmatter
and the room's transcript, the way :func:`assignments.waiting_on` is:

- its progress, as parts settled out of parts;
- its path: the parts in the order ``depends-on`` between them puts them, as
  steps, where a step holds the parts that can run side by side;
- each part's state, and its latest line (the newest thing said in its thread).

The app and the CLI both draw what this returns, so the two can't disagree
about an epic. The field names and states are frozen in
``contracts/board-vocabulary.json`` under ``epic``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services import assignments, tasks
from app.services.agent_registry import norm_handle
from app.services.filesystem import EPISODE_META, get_room_dir, list_memory_files, system_meta

#: Where a part stands, worst-to-best is not the point: these are what a person
#: is told. ``done``: settled. ``blocked``: someone said it can't go on.
#: ``waiting``: it waits on a row that isn't settled. ``working``: someone has
#: it. ``open``: nobody has it yet.
PART_STATES = ("done", "blocked", "waiting", "working", "open")

#: How much of a thread's newest message a part carries as its latest line.
LATEST_CHARS = 280

#: Rows the board lists. ``status/`` rows are reports on how things stand, not
#: work anyone picks up, so they are read (a task can wait on one) but not listed.
LISTED_NAMESPACES = tasks.BOARD_NAMESPACES - {"status"}

PARENT_RELATION = assignments.PARENT_RELATION
BLOCKED_FIELD = "blocked_by"


def title_of(key: str, content: str) -> str:
    """A row's title: the first line of its text, else its key."""
    first = next((ln.strip() for ln in (content or "").splitlines() if ln.strip()), key)
    return first.lstrip("# ").strip() or key


def parent_of(meta: dict) -> str | None:
    """The row ``meta`` says it's a part of, as written."""
    raw = meta.get(PARENT_RELATION)
    if isinstance(raw, list):
        raw = next((v for v in raw if isinstance(v, str) and v.strip()), None)
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _first_line(text: str) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if len(line) <= LATEST_CHARS:
        return line
    head = line[:LATEST_CHARS]
    space = head.rfind(" ")
    return (head[:space] if space > LATEST_CHARS * 0.6 else head).rstrip() + "…"


def latest_lines(room: str) -> dict[str, dict[str, Any]]:
    """The newest thing said in each thread, keyed by its episode URN."""
    from app.services.persister import prose_messages

    latest: dict[str, dict[str, Any]] = {}
    for message in prose_messages(room):
        text = message.content if isinstance(message.content, str) else ""
        if not message.episode or not text.strip():
            continue
        latest[message.episode] = {
            "sender": message.sender_handle,
            "text": _first_line(text),
            "at": message.created_at.isoformat() if message.created_at else None,
        }
    return latest


class _Rows:
    """One read of the room's board rows, and what is derived from them."""

    def __init__(self, room: str, now: datetime) -> None:
        self.room = room
        self.now = now
        self.rows: dict[str, tuple[dict, str]] = {}
        room_dir = get_room_dir(room)
        for namespace in sorted(tasks.BOARD_NAMESPACES):
            for key, meta, content in list_memory_files(
                room_dir, prefix=f"{namespace}/", limit=None
            ):
                self.rows[key] = (meta, content)
        self.children: dict[str, list[str]] = {}
        for key, (meta, _content) in self.rows.items():
            parent = parent_of(meta)
            if parent and parent in self.rows and parent != key:
                self.children.setdefault(parent, []).append(key)
        for parts in self.children.values():
            parts.sort(key=self._created)
        self._latest: dict[str, dict[str, Any]] | None = None

    def _created(self, key: str) -> tuple[str, str]:
        return (str(self.rows[key][0].get("created_at") or ""), key)

    @property
    def latest(self) -> dict[str, dict[str, Any]]:
        if self._latest is None:
            self._latest = latest_lines(self.room)
        return self._latest

    def settled(self, key: str) -> bool:
        return assignments.settled(self.rows[key][0], self.now)

    def waiting_on(self, key: str) -> list[str]:
        meta = self.rows[key][0]
        return [
            dep
            for dep in assignments.dependencies(meta)
            if dep in self.rows and dep != key and not self.settled(dep)
        ]

    def state(self, key: str) -> str:
        meta = self.rows[key][0]
        if self.settled(key):
            return "done"
        if meta.get(BLOCKED_FIELD):
            return "blocked"
        if self.waiting_on(key):
            return "waiting"
        return "working" if assignments.holder(meta, self.now) else "open"

    def part(self, key: str) -> dict[str, Any]:
        meta, content = self.rows[key]
        episode = system_meta(meta).get(EPISODE_META)
        assignee = str(meta.get(assignments.ASSIGNEE_FIELD) or "").lstrip("@") or None
        parts = self.children.get(key, [])
        return {
            "key": key,
            "title": title_of(key, content),
            "episode": episode,
            "state": self.state(key),
            "holder": assignments.holder(meta, self.now),
            "assignee": assignee,
            "waiting_on": self.waiting_on(key),
            "blocked_by": str(meta.get(BLOCKED_FIELD) or "") or None,
            "latest": self.latest.get(episode) if episode else None,
            "parts": len(parts),
            "parts_done": sum(1 for p in parts if self.settled(p)),
            "updated_at": str(meta.get("updated_at") or "") or None,
        }

    def steps(self, parts: list[str]) -> list[list[str]]:
        """``parts`` in path order: each step after every step it depends on.

        A part's step is one past the furthest of the sibling parts it depends
        on, so parts that wait on nothing among themselves share a step and run
        side by side. A dependency outside the epic doesn't move a part along
        its path (it shows as what the part waits on). A cycle can't be
        ordered, so whatever is caught in one goes last, together.
        """
        siblings = set(parts)
        deps = {
            p: [d for d in assignments.dependencies(self.rows[p][0]) if d in siblings and d != p]
            for p in parts
        }
        depth: dict[str, int] = {}
        visiting: set[str] = set()

        def place(p: str) -> int | None:
            if p in depth:
                return depth[p]
            if p in visiting:
                return None
            visiting.add(p)
            below = [place(d) for d in deps[p]]
            visiting.discard(p)
            if any(b is None for b in below):
                return None
            depth[p] = 1 + max((b for b in below if b is not None), default=-1)
            return depth[p]

        for p in parts:
            place(p)
        tangled = [p for p in parts if p not in depth]
        last = max(depth.values(), default=-1)
        for p in tangled:
            depth[p] = last + 1
        steps: list[list[str]] = [[] for _ in range(max(depth.values(), default=-1) + 1)]
        for p in parts:  # already in creation order
            steps[depth[p]].append(p)
        return steps

    def lead(self, key: str) -> str | None:
        """Who leads an epic: whoever holds it, else whoever wrote all its parts."""
        meta = self.rows[key][0]
        if who := assignments.holder(meta, self.now):
            return who
        authors = {
            norm_handle(str(self.rows[p][0].get("created_by") or "")) or ""
            for p in self.children.get(key, [])
        }
        authors.discard("")
        return authors.pop() if len(authors) == 1 else None

    def epic(self, key: str) -> dict[str, Any]:
        parts = self.children.get(key, [])
        return {
            **self.part(key),
            "lead": self.lead(key),
            "done": sum(1 for p in parts if self.settled(p)),
            "total": len(parts),
            "steps": self.steps(parts),
            "path": [self.part(p) for p in parts],
        }

    def inside_open_epic(self, key: str) -> bool:
        parent = parent_of(self.rows[key][0])
        return bool(parent and parent in self.rows and not self.settled(parent))


def board(room: str, now: datetime) -> dict[str, Any]:
    """The room's open epics, and its open tasks that are part of none.

    ``status/`` rows are left out (:data:`LISTED_NAMESPACES`). An epic nested in another open epic is drawn as a part of it, not again at
    the top. A settled epic, or a settled task, leaves the board; both stay in
    the room's memory.
    """
    rows = _Rows(room, now)
    epics: list[dict[str, Any]] = []
    loose: list[dict[str, Any]] = []
    for key in sorted(rows.rows, key=rows._created):
        if key.split("/", 1)[0] not in LISTED_NAMESPACES:
            continue
        if rows.settled(key) or rows.inside_open_epic(key):
            continue
        if rows.children.get(key):
            epics.append(rows.epic(key))
        else:
            loose.append(rows.part(key))
    return {"epics": epics, "tasks": loose}


def show(room: str, key: str, now: datetime) -> dict[str, Any] | None:
    """One row as the board reads it, settled or not: an epic with its path,
    or a task with an empty one. ``None`` when it isn't a board row."""
    rows = _Rows(room, now)
    if key not in rows.rows:
        return None
    return rows.epic(key)
