# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What each wake delivered to an agent, kept per room.

When an agent misses something, the transcript can't tell "it was told and
ignored it" from "it was never woken with it". This keeps the second half in
``log/wakes.jsonl`` beside the transcript: who each wake was for, why it was
raised, which messages it covered, and whether it reached the agent.

**Written as it happens, so a restart loses nothing.** A wake the hub hands to
a runner is written at once, as ``handed``. When the runner says what became of
it, a short line carrying only its ``id`` and the outcome is appended, and
:func:`read` folds the two into one record. The file stays append-only, and a
wake handed just before the hub restarts is still there afterwards, as
``handed``, rather than missing (which would read as "never woken").

**Settled once.** The first outcome for a wake is the one kept; a report
repeated, or one for a wake the log never saw, records nothing.

**Ids only, never text.** The transcript has the text; a record names the
messages by id, so a reader joins the two.

**Bounded.** The file is rotated to ``wakes.1.jsonl`` past :data:`MAX_BYTES`,
keeping one generation, so a busy room's log stays a few megabytes at most.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.filesystem import get_room_dir

FILENAME = "log/wakes.jsonl"
ROTATED = "log/wakes.1.jsonl"
#: Past this the file is rotated, keeping one older generation beside it.
MAX_BYTES = 2_000_000

#: What can become of a wake. ``handed``: given to a runner, which hasn't said
#: (or is from before runners said). ``delivered``: the runner typed it to the
#: agent. ``dropped``: thrown away (held too long, no pane, refused).
#: ``unreached``: a mention of an agent nothing runs, so nothing could be woken;
#: the message isn't lost, and the agent reads it on its next ``await``.
OUTCOMES = frozenset({"handed", "delivered", "dropped", "unreached"})

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _path(room: str) -> Path:
    return get_room_dir(room) / FILENAME


def _write(room: str, record: dict[str, Any]) -> None:
    path = _path(room)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with _lock:
        try:
            if path.stat().st_size + len(line) > MAX_BYTES:
                path.replace(get_room_dir(room) / ROTATED)
        except FileNotFoundError:
            pass
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def _lines(room: str) -> list[dict[str, Any]]:
    """Every line in ``room``'s log, oldest first, across the rotated file."""
    out: list[dict[str, Any]] = []
    for name in (ROTATED, FILENAME):
        try:
            text = (get_room_dir(room) / name).read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                out.append(record)
    return out


def base(room: str, wake: dict[str, Any]) -> dict[str, Any]:
    """The fields every record of ``wake`` carries."""
    record: dict[str, Any] = {
        "id": wake.get("id"),
        "room": room,
        "agent": wake.get("handle"),
        "reason": wake.get("reason") or "mention",
    }
    for src, dst in (("from", "from"), ("episode", "episode"), ("key", "task")):
        if wake.get(src):
            record[dst] = wake[src]
    return record


def handed(room: str, wake: dict[str, Any], covered: dict[str, Any]) -> None:
    """``wake`` was handed to a runner to deliver, covering ``covered``."""
    _write(room, {**base(room, wake), **covered, "at": _now(), "outcome": "handed"})


def dropped(room: str, wake: dict[str, Any], why: str, *, outcome: str = "dropped") -> None:
    """The hub couldn't hand ``wake`` to anyone: ``dropped`` it, or found the
    agent ``unreached``."""
    _write(room, {**base(room, wake), "at": _now(), "outcome": outcome, "why": why})


def report(room: str, wake_id: str, *, delivered: bool, why: str | None = None) -> bool:
    """A runner's word on a wake it was handed, appended as a line naming its id.

    ``False`` (and nothing written) for a wake the log never handed, or one
    already settled, so a repeated report records nothing twice.
    """
    lines = [r for r in _lines(room) if r.get("id") == wake_id]
    if not lines or any(r.get("settles") for r in lines):
        return False
    line: dict[str, Any] = {
        "id": wake_id,
        "settles": True,
        "at": _now(),
        "outcome": "delivered" if delivered else "dropped",
    }
    if why:
        line["why"] = why
    _write(room, line)
    return True


def read(room: str, *, agent: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """The newest wakes in ``room``, newest first, each with its outcome folded in."""
    records: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for n, line in enumerate(_lines(room)):
        key = str(line.get("id") or f"#{n}")
        if line.get("settles"):
            record = records.get(key)
            # The first outcome settles it; a later one changes nothing.
            if record is not None and record.get("outcome") == "handed":
                record.update(
                    {k: v for k, v in line.items() if k in ("outcome", "why")},
                    settled_at=line.get("at"),
                )
            continue
        if key not in records:
            order.append(key)
        records[key] = dict(line)
    newest = [records[k] for k in reversed(order)]
    if agent is not None:
        newest = [r for r in newest if r.get("agent") == agent]
    return newest[:limit]
