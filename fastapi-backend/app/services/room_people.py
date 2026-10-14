# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The people in a room: who joined it, recorded, never guessed from who posted.

A room's people are kept in ``.people.json`` beside its ``.room.json``: one
entry per person, with when they joined and how. A person is someone with a
user record (``users/<handle>``) who is not an agent or engine in the room;
nothing else is ever written here, so an agent whose manifest is missing for a
moment (a restart, a room it was never registered in) can't land among them.

How someone joins (``via``):

- ``created``: they made the room (its ``owner``).
- ``added``: someone put them in it (``POST /rooms/{room}/members``, or a
  private room's ``members`` list).
- ``message``: they posted in it, as a person, from the app or the CLI.
- ``seeded``: they were there before rooms kept a list. The first read of a
  room with no ``.people.json`` writes one from what the app used to infer
  (the owner, a private room's members, agent owners, posters and whoever is
  present), keeping only handles with a user record.

A removed person stays out until they join again. The roster read
(:func:`roster`) adds the room's agents and engines from their manifests, and
``others``: handles that hold a task or are present but are neither, listed so
a member with no manifest yet isn't lost, and never drawn as a person.

Its own file rather than a key in ``.room.json`` because the routes that write
that sidecar rewrite it whole from the fields they know.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.services import principals
from app.services.agent_registry import norm_handle, room_agents
from app.services.filesystem import (
    UnsafePathError,
    get_room_dir,
    list_memory_files,
    read_room_meta,
    room_exists,
    room_path,
)

logger = logging.getLogger(__name__)

FILENAME = ".people.json"

Via = Literal["created", "added", "message", "seeded"]

_lock = threading.Lock()


def _path(room: str) -> Path:
    return room_path(room) / FILENAME


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read(room: str) -> list[dict[str, Any]] | None:
    """The stored entries, or None when the room has no list yet."""
    try:
        text = _path(room).read_text(encoding="utf-8")
    except (FileNotFoundError, UnsafePathError):
        return None
    except OSError:
        logger.warning("room %s: unreadable %s; treating as none", room, FILENAME)
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("room %s: malformed %s; treating as none", room, FILENAME)
        return None
    entries = data.get("people") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict) and norm_handle(e.get("handle"))]


def _write(room: str, entries: list[dict[str, Any]]) -> None:
    path = get_room_dir(room) / FILENAME
    # Written beside the target and renamed over it, so a reader never sees half a file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".people.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"people": entries}, fh, indent=2)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def can_be_person(room: str, handle: str) -> bool:
    """A handle with a user record that isn't an agent or engine in ``room``."""
    return principals.classify_sender(room, handle) == "user"


def _seed_candidates(room: str) -> list[tuple[str, str | None]]:
    """``(handle, first seen)`` for everyone the app used to call a person here."""
    from app.services import room_channels
    from app.services.persister import load_transcript

    found: dict[str, str | None] = {}

    def see(raw: object, at: str | None = None) -> None:
        handle = norm_handle(raw)
        if handle and handle not in found:
            found[handle] = at

    meta = read_room_meta(room) or {}
    see(meta.get("owner"), meta.get("created_at"))
    for member in meta.get("members") or []:
        see(member)
    for agent in room_agents(room):
        see(agent.owner)
    for record in load_transcript(room):
        see(record.sender, record.recorded_at)
    for handle in room_channels.manager.presence(room):
        see(handle)
    return list(found.items())


def _entries(room: str) -> list[dict[str, Any]]:
    """The room's list, seeding it once when there is none. Call under the lock."""
    stored = _read(room)
    if stored is not None:
        return stored
    seeded = [
        {"handle": handle, "joined_at": at or _now(), "via": "seeded"}
        for handle, at in _seed_candidates(room)
        if can_be_person(room, handle)
    ]
    _write(room, seeded)
    return seeded


def start(room: str, owner: object, members: list[str]) -> None:
    """Begin a new room's list: its owner joined by making it, and anyone named with it."""
    at = _now()
    entries: list[dict[str, Any]] = []
    for raw, via in [(owner, "created"), *((m, "added") for m in members)]:
        handle = norm_handle(raw)
        if handle and can_be_person(room, handle) and all(e["handle"] != handle for e in entries):
            entries.append({"handle": handle, "joined_at": at, "via": via})
    with _lock:
        _write(room, entries)


def people(room: str) -> list[dict[str, Any]]:
    """The room's people, in the order they joined, each still a person here."""
    if not room_exists(room):
        return []
    with _lock:
        entries = _entries(room)
    return [e for e in entries if can_be_person(room, e["handle"])]


def handles(room: str) -> set[str]:
    """The handles of the room's people, without checking them again."""
    if not room_exists(room):
        return set()
    with _lock:
        return {norm_handle(e["handle"]) or "" for e in _entries(room)} - {""}


def add(room: str, raw: object, via: Via) -> bool:
    """Record ``raw`` as one of the room's people. True when that's new.

    Refused (False) for a handle that isn't a person: no user record, or an
    agent or engine in this room.
    """
    handle = norm_handle(raw)
    if not handle or not room_exists(room) or not can_be_person(room, handle):
        return False
    with _lock:
        entries = _entries(room)
        if any(e["handle"] == handle for e in entries):
            return False
        entries.append({"handle": handle, "joined_at": _now(), "via": via})
        _write(room, entries)
    return True


def remove(room: str, raw: object) -> bool:
    """Take ``raw`` out of the room's people. True when they were in it."""
    handle = norm_handle(raw)
    if not handle or not room_exists(room):
        return False
    with _lock:
        entries = _entries(room)
        kept = [e for e in entries if e["handle"] != handle]
        if len(kept) == len(entries):
            return False
        _write(room, kept)
    return True


def joined_by_message(room: str, sender: object) -> bool:
    """A person who posts in a room has joined it. Agents and unknown handles haven't."""
    handle = norm_handle(sender)
    if not handle or handle in handles(room):
        return False
    return add(room, handle, "message")


def _task_holders(room: str) -> set[str]:
    from app.services import assignments

    now = datetime.now(UTC)
    held: set[str] = set()
    for key, meta, _content in list_memory_files(get_room_dir(room), limit=None):
        if not assignments.assignable(key):
            continue
        who = norm_handle(assignments.holder(meta, now))
        if who:
            held.add(who)
    return held


def roster(room: str) -> dict[str, list[dict[str, Any]]]:
    """Everyone in a room, from records: people, agents, engines and others."""
    from app.services import room_channels

    agents: list[dict[str, Any]] = []
    engines: list[dict[str, Any]] = []
    for agent in room_agents(room):
        entry = {"handle": agent.handle, "owner": agent.owner}
        (engines if agent.adapter == principals.ENGINE_ADAPTER else agents).append(entry)
    members = people(room)
    known = (
        {norm_handle(a["handle"]) for a in agents + engines} | {e["handle"] for e in members}
    ) - {None}
    held = _task_holders(room)
    present = {norm_handle(h) for h in room_channels.manager.presence(room)} - {None}
    others = [
        {"handle": h, "holds_task": h in held, "present": h in present}
        for h in sorted((held | present) - known)
        if h
    ]
    return {"people": members, "agents": agents, "engines": engines, "others": others}
