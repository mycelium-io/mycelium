# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Bringing one subject's stored data up to date, once, and writing it down.

A migration is an id, one sentence saying what it does, and a function, run for
one subject (a person, an agent, a room) the first time the hub sees it after
the migration was added: for a change the hub can only make once it learns
something, like a person's short handle, which it knows only when they sign in.

Each run is written to a ledger in the hub's data folder (``migrations.jsonl``:
the migration's id, its subject, when, and what it changed), so it never runs
twice for a subject, and an operator can read what was done to their store.

A run that fails or is stopped isn't recorded, so it runs again the next time
the subject turns up. A migration has to be safe to run again over a store it
partly changed: each step checks before it moves anything.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.services.filesystem import get_data_dir

logger = logging.getLogger(__name__)

#: The ledger's file, in the data folder.
LEDGER = "migrations.jsonl"

#: What a migration returns: what it changed, for the ledger (or ``None``).
Changed = dict[str, Any] | None
Run = Callable[..., Changed | Awaitable[Changed]]


@dataclass(frozen=True)
class Migration:
    id: str
    says: str
    #: Called with the subject, then whatever :func:`once` was given.
    run: Run


_registered: dict[str, Migration] = {}
_ledger_lock = threading.Lock()
_subject_locks: dict[tuple[str, str], asyncio.Lock] = {}
#: What this process has seen applied, so a check made on every request (a
#: person's sign-in) doesn't read the ledger each time. Only grows.
_seen: set[tuple[str, str]] = set()


def register(migration: Migration) -> Migration:
    """Add ``migration``; its id must be new."""
    if migration.id in _registered:
        msg = f"migration {migration.id!r} is already registered"
        raise ValueError(msg)
    _registered[migration.id] = migration
    return migration


def _ledger() -> Path:
    return get_data_dir() / LEDGER


def applied() -> list[dict[str, Any]]:
    """Every run the ledger records, oldest first."""
    try:
        lines = _ledger().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    done: list[dict[str, Any]] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            done.append(entry)
    return done


def is_applied(migration_id: str, subject: str) -> bool:
    if (migration_id, subject) in _seen:
        return True
    done = any(e["id"] == migration_id and e.get("subject") == subject for e in applied())
    if done:
        _seen.add((migration_id, subject))
    return done


def _record(migration_id: str, subject: str, changed: Changed) -> None:
    entry: dict[str, Any] = {
        "id": migration_id,
        "subject": subject,
        "at": datetime.now(UTC).isoformat(),
    }
    if changed:
        entry["changed"] = changed
    with _ledger_lock, _ledger().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    _seen.add((migration_id, subject))


def forget_seen() -> None:
    """Drop what this process remembers of the ledger (for tests, and a data
    folder that changed under a running hub)."""
    _seen.clear()


async def once(migration_id: str, subject: str, *args: Any) -> bool:
    """Run ``migration_id`` for ``subject`` if it hasn't been, passing ``args``
    after the subject. ``True`` when it ran now; a failure raises, unrecorded."""
    migration = _registered[migration_id]
    if is_applied(migration_id, subject):
        return False
    lock = _subject_locks.setdefault((migration_id, subject), asyncio.Lock())
    async with lock:
        if is_applied(migration_id, subject):
            return False
        result = migration.run(subject, *args)
        changed = cast("Changed", await result if inspect.isawaitable(result) else result)
        _record(migration_id, subject, changed)
        logger.info("migration %s for %s: %s", migration_id, subject, migration.says)
        return True
