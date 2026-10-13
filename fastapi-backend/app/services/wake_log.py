# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What each wake delivered to an agent, kept per room.

When an agent misses something, the transcript can't tell "it was told and
ignored it" from "it was never woken with it". This keeps the second half: one
line per wake in ``log/wakes.jsonl`` beside the transcript, saying who it was
for, why it was raised, which messages it covered, and whether it reached the
agent or was dropped and why.

**One line per wake.** A wake the hub hands to a runner is kept here, in
memory, until the runner says whether it reached the agent (``report``), then
written once with that outcome. A runner from before reports nothing, so a
handed wake is written as ``handed`` once :data:`REPORT_WAIT_S` passes without
a report. A wake the hub drops itself (held too long) is written at once.

**Ids only, never text.** The transcript has the text; a record names the
messages by id, so a reader joins the two.

**Bounded.** The file is rotated to ``wakes.1.jsonl`` past :data:`MAX_BYTES`,
keeping one generation, so a busy room's log stays a few megabytes at most.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.filesystem import get_room_dir

FILENAME = "log/wakes.jsonl"
ROTATED = "log/wakes.1.jsonl"
#: Past this the file is rotated, keeping one older generation beside it.
MAX_BYTES = 2_000_000
#: How long a handed wake waits for its runner to say what happened.
REPORT_WAIT_S = 120.0

#: What can happen to a wake.
OUTCOMES = frozenset({"delivered", "dropped", "handed"})

_lock = threading.Lock()
#: Handed wakes awaiting their runner's report: ``{(room, id): (record, monotonic)}``.
_pending: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}


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
    flush(room)
    record = {**base(room, wake), **covered, "handed_at": _now()}
    if not record.get("id"):
        record["outcome"] = "handed"
        _write(room, record)
        return
    with _lock:
        _pending[(room, str(record["id"]))] = (record, time.monotonic())


def dropped(room: str, wake: dict[str, Any], why: str) -> None:
    """The hub dropped ``wake`` without handing it to anyone."""
    _write(room, {**base(room, wake), "at": _now(), "outcome": "dropped", "why": why})


def report(room: str, wake_id: str, *, delivered: bool, why: str | None = None) -> bool:
    """A runner's word on a wake it was handed. ``False`` for one not awaited
    (unknown, or already written), so nothing is recorded twice."""
    with _lock:
        entry = _pending.pop((room, wake_id), None)
    if entry is None:
        return False
    record = {**entry[0], "at": _now(), "outcome": "delivered" if delivered else "dropped"}
    if why:
        record["why"] = why
    _write(room, record)
    return True


def flush(room: str, *, now: float | None = None) -> None:
    """Write the handed wakes in ``room`` whose runner never reported, as ``handed``."""
    now = time.monotonic() if now is None else now
    with _lock:
        late = [
            key for key, (_, at) in _pending.items() if key[0] == room and now - at >= REPORT_WAIT_S
        ]
        records = [_pending.pop(key)[0] for key in late]
    for record in records:
        _write(room, {**record, "at": _now(), "outcome": "handed", "why": "the runner didn't say"})


def read(room: str, *, agent: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """The newest records in ``room``, newest first, with any still awaiting a
    report (``outcome: pending``) ahead of them."""
    flush(room)
    lines: list[str] = []
    for name in (ROTATED, FILENAME):
        try:
            lines += (get_room_dir(room) / name).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
    records: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and (agent is None or record.get("agent") == agent):
            records.append(record)
    with _lock:
        waiting = [
            {**r, "outcome": "pending"}
            for (r_room, _), (r, _) in _pending.items()
            if r_room == room and (agent is None or r.get("agent") == agent)
        ]
    return (list(reversed(waiting)) + records)[:limit]


def reset() -> None:
    """Forget every handed wake awaiting a report. For tests."""
    with _lock:
        _pending.clear()
