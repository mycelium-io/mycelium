# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent's subagents: members with a handle of their own, recorded with their parent.

A subagent runs inside its parent's process (Claude Code, Cursor, Codex), so it
posts as its parent unless the parent gives it a handle of its own. That handle
is the parent's, a colon, then the subagent's name: ``builder:review``. A colon
is outside the handle pattern, so no person or agent is ever named like one, and
nothing a person picks is reserved.

The link to the parent is recorded here, never read from the name:
``mycelium subagent start`` records it, and only a recorded subagent shows as one
or can be acted as by its parent's token. Records are kept per room, in
``.subagents.json``, and an ended one stays, so its messages still read as the
parent's subagent after it's gone.

A subagent is ``working`` until its step in the parent's work ends, then
``done`` for a moment, then ``ended``. What ends it:

- ``mycelium subagent end``;
- its step finishing in the parent's session file, which the runner reports as
  a count of the parent's finished subagent steps (one that only goes up, so a
  step that opened and closed between two heartbeats still counts), and of its
  open ones, for a runner too old to send the first;
- its parent stopping, since it runs in the parent's process;
- a timeout, for a runner that never says.

A row a subagent claimed goes back to the board when it ends
(:func:`release_ended`), so nothing is left held by a handle that's gone.

Known limits: the counts are per parent, not per subagent, so with several
running, finished steps are matched to them oldest first, and a subagent step
the parent ran without ``subagent start`` counts too. Ended records are kept
for good, and the whole list is what every open Members rail reads.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.services.agent_registry import norm_handle
from app.services.filesystem import room_exists, room_path

FILENAME = ".subagents.json"
SEPARATOR = ":"

State = Literal["working", "done", "ended"]

#: How long a done subagent is still listed, faded, before it leaves.
DONE_FOR = timedelta(minutes=2)
#: A subagent nobody has reported on in this long is ended.
TIMEOUT = timedelta(hours=6)
#: What a subagent's own name may be.
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")

_lock = threading.Lock()
#: The finished-step count each parent's runner last sent, by (room, parent),
#: so a subagent started between heartbeats counts from where its parent was.
#: Kept in memory: after a restart, a subagent counts from the next heartbeat.
_last_finished: dict[tuple[str, str], int] = {}


class SubagentError(ValueError):
    def __init__(self, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def handle_of(parent: str, name: str) -> str:
    return f"{parent}{SEPARATOR}{name}"


def _read(room: str) -> list[dict[str, Any]]:
    try:
        data = json.loads((room_path(room) / FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("subagents") if isinstance(data, dict) else None
    return [e for e in entries or [] if isinstance(e, dict) and isinstance(e.get("handle"), str)]


def _write(room: str, entries: list[dict[str, Any]]) -> None:
    path = room_path(room) / FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"subagents": entries}, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _settle(entries: list[dict[str, Any]], now: datetime) -> bool:
    """Move each record on as time says: a done one ends after :data:`DONE_FOR`,
    a working one after :data:`TIMEOUT`. Whether anything changed."""
    changed = False
    for e in entries:
        if (e.get("state") == "done" and now - _at(e.get("done_at"), now) >= DONE_FOR) or (
            e.get("state") == "working" and now - _at(e.get("started_at"), now) >= TIMEOUT
        ):
            e.update(state="ended", ended_at=now.isoformat())
            changed = True
    return changed


def _at(raw: object, default: datetime) -> datetime:
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return default


def records(room: str) -> list[dict[str, Any]]:
    """Every subagent the room has had, ended ones included, oldest first."""
    if not room_exists(room):
        return []
    with _lock:
        entries = _read(room)
        if _settle(entries, _now()):
            _write(room, entries)
        return entries


def record(room: str, handle: str) -> dict[str, Any] | None:
    wanted = norm_handle(handle)
    return next((e for e in records(room) if e["handle"] == wanted), None)


def parent_of(room: str, handle: str) -> str | None:
    """The parent of a subagent that hasn't ended, recorded in ``room``."""
    found = record(room, handle)
    return found["parent"] if found and found.get("state") != "ended" else None


def start(room: str, parent: str, name: str) -> dict[str, Any]:
    """Record ``parent``'s subagent ``name``; starting one that's already
    there starts it again."""
    me = norm_handle(parent)
    wanted = norm_handle(name)
    if not me or SEPARATOR in me:
        msg = "A subagent's parent is an agent or a person, not another subagent."
        raise SubagentError(msg)
    if not wanted or not _NAME.match(wanted):
        msg = "A subagent's name is lowercase letters, digits, and . _ or -, up to 48 of them."
        raise SubagentError(msg)
    handle = handle_of(me, wanted)
    now = _now().isoformat()
    with _lock:
        entries = [e for e in _read(room) if e["handle"] != handle]
        entry = {
            "handle": handle,
            "parent": me,
            "name": wanted,
            "state": "working",
            "started_at": now,
            "seen_open": False,
        }
        if (base := _last_finished.get((room, me))) is not None:
            entry["finished_base"] = base
        entries.append(entry)
        _write(room, entries)
    return entry


def end(room: str, handle: str) -> dict[str, Any] | None:
    """End a subagent; ``None`` when the room has none by that handle."""
    wanted = norm_handle(handle)
    with _lock:
        entries = _read(room)
        found = next((e for e in entries if e["handle"] == wanted), None)
        if found is None:
            return None
        if found.get("state") != "ended":
            found.update(state="ended", ended_at=_now().isoformat())
            _write(room, entries)
        return found


def observe(
    room: str,
    parent: str,
    open_steps: int | None,
    parent_state: str | None,
    *,
    finished_steps: int | None = None,
) -> None:
    """What the parent's machine says: how many subagent steps are open in its
    session file and how many have finished (each ``None`` when its CLI's
    file isn't read), and the parent's own state. Its working subagents follow.

    The counts are the parent's, not any one subagent's. Each finished step
    since a subagent started ends one working subagent, oldest first; with
    several running, the one that ends may not be the one whose step finished,
    and the others still end as their own steps do. Without a finished count
    (an older runner), a subagent is done once its parent has no subagent step
    open, after one was seen open, so with two running the first to finish
    shows working until both are done.
    """
    me = norm_handle(parent)
    if not me or not room_exists(room):
        return
    now = _now()
    with _lock:
        entries = _read(room)
        changed = _settle(entries, now)
        mine = sorted(
            (e for e in entries if e.get("parent") == me and e.get("state") != "ended"),
            key=lambda e: str(e.get("started_at") or ""),
        )
        if parent_state in ("stopped", "gone"):
            for e in mine:
                e.update(state="ended", ended_at=now.isoformat())
                changed = True
        elif finished_steps is not None:
            changed = _follow_finished(room, me, mine, finished_steps, now) or changed
        elif open_steps is not None:
            changed = _follow_open(mine, open_steps, now) or changed
        if changed:
            _write(room, entries)


def _follow_finished(
    room: str, parent: str, mine: list[dict[str, Any]], finished: int, now: datetime
) -> bool:
    """End working subagents by the parent's finished-step count. A count
    lower than one already seen means the runner started again, so every
    subagent counts from the new one."""
    last = _last_finished.get((room, parent))
    _last_finished[(room, parent)] = finished
    working = [e for e in mine if e.get("state") == "working"]
    changed = False
    for e in working:
        base = e.get("finished_base")
        if base is None or (last is not None and finished < last) or finished < base:
            e["finished_base"] = finished
            changed = True
    # Oldest first, each finished step ends one subagent, and is then no
    # longer counted for the younger ones.
    for i, e in enumerate(working):
        if finished - int(e["finished_base"]) > 0:
            e.update(state="done", done_at=now.isoformat())
            for younger in working[i + 1 :]:
                younger["finished_base"] = int(younger["finished_base"]) + 1
            changed = True
    return changed


def _follow_open(mine: list[dict[str, Any]], open_steps: int, now: datetime) -> bool:
    changed = False
    for e in mine:
        if e.get("state") != "working":
            continue
        if open_steps > 0 and not e.get("seen_open"):
            e["seen_open"] = True
            changed = True
        elif open_steps == 0 and e.get("seen_open"):
            e.update(state="done", done_at=now.isoformat())
            changed = True
    return changed


async def release_ended(room: str) -> list[str]:
    """Hand back the rows each subagent that has ended (or is done) was
    holding, once per subagent, so the board never shows a row held by a
    handle that's gone. Returns the rows."""
    from app.services import assignments

    if not room_exists(room):
        return []
    now = _now()
    with _lock:
        entries = _read(room)
        _settle(entries, now)
        due = [e for e in entries if e.get("state") != "working" and not e.get("released")]
        for e in due:
            e["released"] = True
        if due:
            _write(room, entries)
    released: list[str] = []
    for e in due:
        for key in assignments.claimed_by(room, e["handle"], now):
            await assignments.end_hold(
                room, key, f"@{e['handle']} ended", subkind="released", by=e["handle"], now=now
            )
            released.append(key)
    return released
