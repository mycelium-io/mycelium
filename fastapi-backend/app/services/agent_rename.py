# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Renaming an agent: a new handle for the same member of a room.

An agent's name stops fitting as its work changes. A rename moves everything
the room keeps under the old handle to the new one: its manifest and notes
(``agents/<handle>`` and everything under it), the open board rows it is meant
for or holding, its presence, pending doorbell, floors and read positions, and
the schedules it owns, and the room's member list. Nothing keeps the old handle:
it is free the moment the rename is done.

A running agent can't learn a new name from its environment, so an agent on a
connected machine is restarted there under the new one, and nothing changes
until the person at that machine says yes: the route only checks and queues the
``rename`` job (:func:`restart_target` says where), and the hub applies the
rename (:func:`apply`) when the runner, after the yes, asks to go ahead. A
declined or failed job leaves the room exactly as it was. An agent no connected
machine has is renamed at once.

What was said stays as it was said: past messages keep the handle they were
signed with.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, cast

import yaml

from app.schemas import HANDLE_PATTERN
from app.services import assignments, fields, pauses
from app.services.agent_registry import AGENTS_PREFIX, norm_handle
from app.services.filesystem import (
    get_room_dir,
    list_memory_files,
    read_memory_file,
    read_room_meta,
    room_exists,
    unmanaged_meta,
    write_room_meta,
)
from app.services.room_channels import manager

if TYPE_CHECKING:
    from fastapi import Request

logger = logging.getLogger(__name__)

_HANDLE_RE = re.compile(HANDLE_PATTERN)
#: Fields on a board row that name a member, bare or as ``@handle``.
_ROW_FIELDS = ("assignee", "owner", "assignment_note_by")


class RenameError(Exception):
    """A rename refused, with a sentence saying why and the status to answer with."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _manifest(room: str, handle: str) -> dict | None:
    found = read_memory_file(get_room_dir(room), f"{AGENTS_PREFIX}{handle}")
    if found is None:
        return None
    try:
        data = yaml.safe_load(found[1]) or {}
    except yaml.YAMLError:
        data = {}
    return data if isinstance(data, dict) else {}


def check(room: str, old: str, new: str) -> None:
    """Refuse a rename that can't be done, before anything is written."""
    if not room_exists(room):
        raise RenameError("Room not found", status=404)
    manifest = _manifest(room, old)
    if manifest is None:
        raise RenameError(f"No agent @{old} in {room}.", status=404)
    if manifest.get("adapter") == "engine":
        raise RenameError(
            f"@{old} is an engine. Engines are summoned by their handle, so add one under "
            "the new name instead."
        )
    if not new or not _HANDLE_RE.match(new):
        raise RenameError(
            "A handle is lowercase letters, digits, '.', '_', '-' or '@', starting with a "
            "letter or digit."
        )
    if new == old:
        raise RenameError(f"@{old} is already called that.")
    if _manifest(room, new) is not None:
        raise RenameError(f"@{new} is already a member of {room}.", status=409)
    from app.services.principals import classify_sender

    # A person's handle: the agent would post as them and wake on every mention of them.
    if classify_sender(room, new) == "user":
        raise RenameError(f"@{new} is a person's name.", status=409)


def _renamed_value(value: object, old: str, new: str) -> object:
    """``value`` with ``old`` as a handle replaced by ``new``, keeping its ``@``."""
    if not isinstance(value, str) or norm_handle(value) != old:
        return value
    return f"@{new}" if value.strip().startswith("@") else new


async def _copy_memories(room: str, old: str, new: str, by: str) -> tuple[list[str], list[str]]:
    """``agents/<old>`` and everything under it, written under ``new``.

    Returns the keys written and the old keys to remove once nothing names
    ``old`` any more (deleting its manifest releases the rows it holds).
    """
    from app.routes.memory import _reconstruct_value, upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    room_dir = get_room_dir(room)
    base = f"{AGENTS_PREFIX}{old}"
    keys = [base] + [
        key
        for key, _meta, _content in list_memory_files(room_dir, prefix=f"{base}/", limit=None)
        if key.startswith(f"{base}/")
    ]
    moved: list[str] = []
    copied: list[str] = []
    for key in keys:
        found = read_memory_file(room_dir, key)
        if found is None:
            continue
        meta, content = found
        target = f"{AGENTS_PREFIX}{new}{key.removeprefix(base)}"
        value: dict | str = _reconstruct_value(meta, content)
        tags = meta.get("tags")
        item = MemoryCreate(
            key=target,
            value=value,
            embed=False,
            created_by=by,
            tags=list(tags) if isinstance(tags, list) else None,
            meta=unmanaged_meta(meta) or None,
        )
        await upsert_memories(room, MemoryBatchCreate(items=[item]))
        moved.append(target)
        copied.append(key)
    return moved, copied


async def _move_rows(room: str, old: str, new: str, by: str) -> list[str]:
    """Every open board row meant for or held by ``old``, now naming ``new``."""
    changed: list[str] = []
    for key, meta, content in list_memory_files(get_room_dir(room), limit=None):
        if not assignments.assignable(key):
            continue
        patch = {
            f: _renamed_value(meta.get(f), old, new)
            for f in _ROW_FIELDS
            if _renamed_value(meta.get(f), old, new) != meta.get(f)
        }
        if not patch:
            continue
        await fields.upsert_patch(room, key, meta, content, patch, by, notify=False)
        changed.append(key)
    return changed


def _move_room_member(room: str, old: str, new: str) -> None:
    meta = read_room_meta(room)
    if not meta:
        return
    members = meta.get("members")
    if isinstance(members, list) and old in members:
        meta["members"] = sorted({new if m == old else m for m in members})
        write_room_meta(room, meta)


def restart_target(room: str, handle: str) -> str | None:
    """The connected runner whose machine has ``handle`` in ``room`` in a herdr pane.

    Whichever started it: its machine reports every agent in herdr there, so an
    agent brought in by a person is found the same as one the app started.
    ``None`` when no connected machine has it, which the rename says.
    """
    from app.services.runners import registry

    for runner in registry.all():
        if not runner.connected or runner.machine is None:
            continue
        for workspace in runner.machine.workspaces:
            if any(a.room == room and a.handle == handle for a in workspace.agents):
                return runner.id
    return None


def announcement(old: str, new: str) -> str:
    """What the room is told, mentioning the agent under its new name to wake it.

    The old name is written without its ``@``, so the line mentions only the new
    one: a mention of the old name would ask for a member that is gone.
    """
    return f"@{new}: you're @{new} now, renamed from {old}. Your notes are at `agents/{new}/notes`."


async def rename(room: str, old: str, new: str, *, by: str) -> tuple[list[str], list[str]]:
    """Rename ``old`` to ``new`` in ``room``; the memories and rows it moved.

    Checked first (:func:`check`), so a refused rename writes nothing. The room
    isn't told here: :func:`apply` does both.
    """
    from app.routes.memory import delete_memory  # lazy: routes import services
    from app.services import schedules

    old, new = norm_handle(old) or "", norm_handle(new) or ""
    check(room, old, new)
    memories, old_keys = await _copy_memories(room, old, new, by)
    # The rows first: removing the old manifest hands back every row it still
    # holds, as it does when an agent leaves the room.
    rows = await _move_rows(room, old, new, by)
    for key in old_keys:
        await delete_memory(room, key)
    await schedules.rename_owner(room, old, new)
    _move_room_member(room, old, new)
    manager.rename_member(room, old, new)
    pauses.rename(room, old, new)
    logger.info("room %s: @%s renamed to @%s by %s", room, old, new, by)
    return memories, rows


async def apply(room: str, old: str, new: str, *, by: str) -> tuple[list[str], list[str]]:
    """Rename ``old`` to ``new`` and tell the room, as whoever renamed it.

    What the route does for an agent no machine is running, and what the hub
    does for one that is, once its machine said yes.
    """
    from app.routes.messages import send_message  # lazy: routes import services
    from app.schemas import MessageCreate, MessageType

    moved = await rename(room, old, new, by=by)
    # No request: who says it is the person who asked for the rename, recorded
    # when they did.
    await send_message(
        room,
        MessageCreate(
            sender_handle=by,
            message_type=MessageType.BROADCAST,
            content=announcement(old, new),
        ),
        cast("Request", None),
    )
    return moved
