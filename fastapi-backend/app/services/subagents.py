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
- its step ending in the parent's session file, which the runner reports as a
  count of the parent's open subagent steps (only once the step has been seen
  open since the subagent started, so the moment between ``start`` and the
  step beginning doesn't end it);
- its parent stopping, since it runs in the parent's process;
- a timeout, for a runner that never says.
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


def observe(room: str, parent: str, open_steps: int | None, parent_state: str | None) -> None:
    """What the parent's machine says: how many subagent steps are open in its
    session file (``None`` when its CLI's file isn't read), and the parent's
    own state. Its working subagents follow."""
    me = norm_handle(parent)
    if not me or not room_exists(room):
        return
    now = _now()
    with _lock:
        entries = _read(room)
        changed = _settle(entries, now)
        for e in entries:
            if e.get("parent") != me or e.get("state") == "ended":
                continue
            if parent_state in ("stopped", "gone"):
                e.update(state="ended", ended_at=now.isoformat())
                changed = True
            elif e.get("state") != "working" or open_steps is None:
                continue
            elif open_steps > 0 and not e.get("seen_open"):
                e["seen_open"] = True
                changed = True
            elif open_steps == 0 and e.get("seen_open"):
                e.update(state="done", done_at=now.isoformat())
                changed = True
        if changed:
            _write(room, entries)
