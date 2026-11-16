# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Moving a signed-in person from an email-shaped handle to their short one.

A migration (``services/migrations.py``) run once per person, the first time
they sign in after the hub started giving short handles: only then does the hub
know which short handle an email-shaped one became (``services/identities.py``).
It moves the old handle to the new one everywhere the hub keeps a person's
handle: their user record and room folders, and in every room the agents they
own or may act as (``owner``, ``allow_from``), the tasks meant for or held by
them, schedules they own, the room's people and members, and their presence and
read positions. What was said stays as it was said: past messages keep the
handle they were sent with, and the app shows them under the person's name.

Safe to stop halfway: each step checks before it moves anything, and the
migration is recorded only once it finishes, so a stopped one finishes at the
person's next sign-in. Every memory it rewrites is written over the version it
read, and read again when something wrote it in between, so a live edit to an
agent or a task is never lost to it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import yaml
from fastapi import HTTPException

from app.services import migrations
from app.services.agent_registry import AGENTS_PREFIX, norm_handle
from app.services.filesystem import (
    contained,
    delete_memory_file,
    get_data_dir,
    get_users_dir,
    list_memory_files,
    list_room_names,
    read_memory_file,
    read_room_meta,
    room_path,
    unmanaged_meta,
    write_room_meta,
)

logger = logging.getLogger(__name__)

MIGRATION = "people.short_handle"

#: How many times a memory is read and written again when it moved underneath.
RETRIES = 5

#: What a task row names a person by.
_ROW_FIELDS = ("assignee", "owner", "assignment_note_by")

#: How long a move that failed waits before a sign-in tries it again.
RETRY_AFTER_S = 300.0
#: When each person's failed move may be tried again, in this process.
_failed_until: dict[str, float] = {}


def _renamed(value: object, old: str, new: str) -> object:
    """``value`` (a handle, or a list of them) with ``old`` replaced by ``new``."""
    from app.services.agent_rename import _renamed_value

    if isinstance(value, list):
        return [_renamed_value(v, old, new) for v in value]
    return _renamed_value(value, old, new)


Rewrite = Callable[[dict[str, Any], str], Awaitable[bool]]


async def _rewrite(room: str, key: str, write: Rewrite) -> bool:
    """Read ``key`` and hand it to ``write``, which writes it over the version
    it was given and returns ``False`` when there was nothing to change. Read
    again and retried when something wrote it in between."""
    for _ in range(RETRIES):
        found = read_memory_file(room_path(room), key)
        if found is None:
            return False
        try:
            return bool(await write(found[0], found[1]))
        except HTTPException as e:
            if e.status_code != 409:
                raise
    msg = f"{key} in {room} kept changing while its handle was being moved"
    raise RuntimeError(msg)


async def _move_grant(room: str, key: str, old: str, new: str) -> bool:
    """An agent ``old`` owns or may act as, now naming ``new``."""
    from app.routes.memory import upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    async def write(meta: dict[str, Any], content: str) -> bool:
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            return False
        if not isinstance(data, dict):
            return False
        changed = {f: _renamed(data[f], old, new) for f in ("owner", "allow_from") if data.get(f)}
        if all(changed[f] == data[f] for f in changed):
            return False
        data.update(changed)
        tags = meta.get("tags")
        item = MemoryCreate(
            key=key,
            value=yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            created_by=new,
            embed=False,
            tags=list(tags) if isinstance(tags, list) else None,
            meta=unmanaged_meta(meta) or None,
            base_version=meta.get("version"),
        )
        await upsert_memories(room, MemoryBatchCreate(items=[item]), notify=False)
        return True

    return await _rewrite(room, key, write)


async def _move_row(room: str, key: str, old: str, new: str) -> bool:
    """A task meant for, held by or handed back by ``old``, now naming ``new``."""
    from app.services import fields

    async def write(meta: dict[str, Any], content: str) -> bool:
        patch = {f: _renamed(meta.get(f), old, new) for f in _ROW_FIELDS}
        patch = {f: v for f, v in patch.items() if v != meta.get(f)}
        if not patch:
            return False
        await fields.upsert_patch(
            room, key, meta, content, patch, new, notify=False, base_version=meta.get("version")
        )
        return True

    return await _rewrite(room, key, write)


def _move_room_meta(room: str, old: str, new: str) -> bool:
    meta = read_room_meta(room)
    if not meta:
        return False
    changed = False
    if norm_handle(meta.get("owner")) == old:
        meta["owner"] = new
        changed = True
    members = meta.get("members")
    if isinstance(members, list) and old in members:
        meta["members"] = sorted({new if m == old else m for m in members})
        changed = True
    if changed:
        write_room_meta(room, meta)
    return changed


def _move_user(old: str, new: str) -> bool:
    from app.services import principals

    user = principals.load_user(old)
    if user is None:
        return False
    if principals.load_user(new) is None:
        principals.write_user({**user, "handle": new})
    delete_memory_file(get_users_dir(), old)
    return True


def _move_folders(old: str, new: str) -> bool:
    base = get_data_dir() / "preferences"
    src, dst = contained(base, old), contained(base, new)
    if not src.is_dir() or dst.exists():
        return False
    src.rename(dst)
    return True


async def _move_room(room: str, old: str, new: str) -> int:
    from app.services import assignments, pauses, room_people, schedules, subscriptions
    from app.services.room_channels import manager

    moved = 0
    for key, _meta, _content in list_memory_files(room_path(room), limit=None):
        if key.startswith(AGENTS_PREFIX) and "/" not in key.removeprefix(AGENTS_PREFIX):
            moved += await _move_grant(room, key, old, new)
        elif assignments.assignable(key):
            moved += await _move_row(room, key, old, new)
    moved += len(await schedules.rename_owner(room, old, new))
    moved += await subscriptions.rename(room, old, new)
    moved += room_people.rename(room, old, new)
    moved += _move_room_meta(room, old, new)
    manager.rename_member(room, old, new)
    pauses.rename(room, old, new)
    return moved


async def move(old: str, new: str) -> dict[str, Any]:
    """Move ``old`` to ``new`` everywhere the hub keeps a person's handle;
    what moved, for the migration's ledger entry. Safe to run again."""
    changed: dict[str, Any] = {"user": _move_user(old, new), "folders": _move_folders(old, new)}
    rooms: dict[str, int] = {}
    for room in list_room_names():
        count = await _move_room(room, old, new)
        if count:
            rooms[room] = count
    changed["rooms"] = rooms
    logger.info("moved a person's handle to @%s in %d room(s)", new, len(rooms))
    return changed


async def _run(_subject: str, old: str, new: str) -> dict[str, Any]:
    return await move(old, new)


migrations.register(
    migrations.Migration(
        id=MIGRATION,
        says="A signed-in person's email-shaped handle becomes their short one, "
        "everywhere the hub keeps it.",
        run=_run,
    )
)


async def settle(issuer: str, subject: str, claimed: str, handle: str) -> None:
    """Once per person: move what the hub kept under the handle their sign-in
    used to give (``claimed``) to the short one it gives now."""
    old = norm_handle(claimed)
    if not old or old == handle:
        return
    who = f"{issuer} {subject}"
    if time.monotonic() < _failed_until.get(who, 0.0):
        return
    try:
        await migrations.once(MIGRATION, who, old, handle)
    except Exception:
        # Their request goes ahead under the short handle; the move isn't
        # recorded, so it finishes at a later sign-in. Not on every request
        # meanwhile: one that keeps failing would scan every room each time.
        _failed_until[who] = time.monotonic() + RETRY_AFTER_S
        logger.exception("moving a handle to @%s stopped partway; it runs again later", handle)
