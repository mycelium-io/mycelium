# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What is waiting on a member: the one read behind "Waiting on you".

Four things, each worked out on read and never stored:

- **approve**: an agent's ask for the member's decision (:mod:`approvals`)
  that nobody has answered yet. Each is its own item, since each needs its
  own answer.
- **ask**: a message that asks the member (by the one rule, :mod:`asks`) in a
  thread where it hasn't posted since. Several in one thread are one item,
  the newest, with the rest counted.
- **turn**: a flow step whose floor is given to the member right now.
- **task**: an open row the member holds that waits on nothing, is blocked by
  nothing and has no open parts of its own.

An ask in a settled task's thread is not waiting on anyone: the work it was
about is over. Past approvals, each kind appears once per thread, an approval
before an ask before a turn before a task, so one task is never listed twice.

GitHub review requests are left out: the hub knows them as GitHub logins, and
nothing maps a login to a member.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services import message_format
from app.services.agent_registry import norm_handle
from app.services.board import _first_line, _Rows, parent_of, title_of
from app.services.filesystem import EPISODE_META, system_meta

#: The kinds of item, in the order they're listed.
KINDS = ("approve", "ask", "turn", "task")
#: How far back the transcript is read for asks.
SCAN = 2000


def _norm(handle: object) -> str:
    return norm_handle(str(handle or "").partition("#")[0]) or ""


def _records(room: str) -> list[Any]:
    from app.services import room_channels
    from app.services.persister import load_transcript

    managed = room_channels.manager.get(room)
    if managed and managed.persister:
        return managed.persister.log.records
    return load_transcript(room)


def waiting(room: str, handle: str, now: datetime) -> list[dict[str, Any]]:
    """Everything waiting on ``handle`` in ``room``, asks first, newest first."""
    from app.services import approvals
    from app.services.asks import asks
    from app.services.persister import read_id, record_episode
    from app.services.room_channels import manager

    me = _norm(handle)
    if not me:
        return []
    rows = _Rows(room, now)
    by_episode = {
        episode: key
        for key, (meta, _content) in rows.rows.items()
        if (episode := system_meta(meta).get(EPISODE_META))
    }

    def thread_of(record: Any) -> str | None:
        ep = record_episode(record)
        return None if not ep or message_format.is_live_episode(room, ep) else ep

    def about(key: str, episode: str | None) -> dict[str, Any]:
        """The task an item is in, and the epic that task is part of."""
        parent = parent_of(rows.rows[key][0])
        epic = parent if parent in rows.rows else None
        return {
            "key": key,
            "title": title_of(key, rows.rows[key][1]),
            "episode": episode,
            "epic": epic,
            "epic_title": title_of(epic, rows.rows[epic][1]) if epic else None,
        }

    def where(episode: str | None) -> dict[str, Any]:
        key = by_episode.get(episode) if episode else None
        if key is None:
            return {
                "key": None,
                "title": None,
                "episode": episode,
                "epic": None,
                "epic_title": None,
            }
        return about(key, episode)

    items: list[dict[str, Any]] = []
    seen: set[str | None] = set()
    records = _records(room)[-SCAN:]

    # Approvals: an agent's ask for a decision, until it is answered.
    for hit in approvals.open_for(me, records, room):
        thread = thread_of(hit.record)
        key = by_episode.get(thread) if thread else None
        if key is not None and rows.settled(key):
            continue
        items.append(
            {
                "kind": approvals.WAITING_KIND,
                **where(thread),
                "sender": hit.record.sender,
                "text": str(hit.ask.get("question") or ""),
                "message_id": str(read_id(hit.record)),
                "at": hit.record.recorded_at or None,
                "count": 1,
            }
        )
        seen.add(thread)

    # Asks: newest first, one per thread, dropped once the member posted there.
    answered: set[str | None] = set()
    pending: dict[str | None, list[Any]] = {}
    for record in reversed(records):
        thread = thread_of(record)
        if _norm(record.sender) == me:
            answered.add(thread)
            continue
        if thread in answered or thread in seen or approvals.ask_on(record) is not None:
            continue
        if not asks(record.content, me):
            continue
        key = by_episode.get(thread) if thread else None
        if key is not None and rows.settled(key):
            continue
        pending.setdefault(thread, []).append(record)
    for thread, found in pending.items():
        newest = found[0]
        text = str(newest.content.get("content") or "")
        items.append(
            {
                "kind": "ask",
                **where(thread),
                "sender": newest.sender,
                # The line that asks this member, not whoever the message names first.
                "text": _first_line(text, about=me),
                "message_id": str(read_id(newest)),
                "at": newest.recorded_at or None,
                "count": len(found),
            }
        )
        seen.add(thread)

    # Turns: a floor given to the member.
    for floor in manager.floors_of(room):
        if me not in {_norm(s) for s in floor.speakers} or floor.episode in seen:
            continue
        items.append(
            {
                "kind": "turn",
                **where(floor.episode),
                "sender": floor.holder,
                "text": None,
                "message_id": None,
                # How long the turn has been waiting on the member.
                "at": floor.since.isoformat() if floor.since else None,
                "count": 1,
            }
        )
        seen.add(floor.episode)

    # Tasks: open, held by the member, and nothing ahead of them.
    for key in sorted(rows.rows, key=rows._created, reverse=True):
        part = rows.part(key)
        if _norm(part["holder"]) != me or part["state"] != "working":
            continue
        if part["parts"] > part["parts_done"] or (part["episode"] and part["episode"] in seen):
            continue
        items.append(
            {
                "kind": "task",
                **about(key, part["episode"]),
                "sender": None,
                "text": part["latest"]["text"] if part["latest"] else None,
                "message_id": None,
                "at": part["updated_at"],
                "count": 1,
            }
        )
        seen.add(part["episode"])
    return items
