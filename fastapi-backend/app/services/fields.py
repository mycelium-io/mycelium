# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A row's fields are its memory's frontmatter, and a row action writes them.

The board projects a row as a title plus whatever frontmatter its memory
carries, so every row action but an assignment — a status change, a priority, a
block, a dismissal — is a frontmatter write and nothing else.  This is that
write, and it is the same upsert ``memory set --meta`` goes through: versioned,
indexed, link-parsed, broadcast, and readable in a text editor.

**Assignment is the one axis this refuses.**  ``assignment``, ``owner`` and the
lease's companion keys move under rules a field write does not know — a live
claim is not stealable, an expired one is, and expiry is derived from a clock
rather than written down.  A plain field write setting ``owner`` would forge a
claim that passed none of that, so the reserved keys are refused by name and
pointed at the endpoint that does own them.

**Only a memory has fields.**  Episodes, agents and any other projected row are
read out of state that lives elsewhere, so there is no frontmatter to write and
the refusal says so rather than inventing a file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.filesystem import get_room_dir, read_memory_file, unmanaged_meta

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Frontmatter a lease owns.  Frozen in ``contracts/board-vocabulary.json``
#: under ``assignment`` (``field`` + ``companion_fields``) plus the holder itself;
#: ``tests/test_fields.py`` asserts this set against that file.
RESERVED = frozenset(
    {"assignment", "owner", "claimed_at", "ttl_minutes", "assignment_note", "assignment_note_by"}
)

RESERVED_REASON = (
    "assignment moves through the lease endpoints (/assignments/claim, /release, /resolve), "
    "not a field write — a claim has rules a field write cannot check"
)


class FieldError(Exception):
    """A field write the room refuses, with the reason a reader needs."""

    def __init__(self, reason: str, *, status: int = 400, **detail: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.detail = detail


def reserved_in(names: Iterable[str]) -> list[str]:
    """Which of ``names`` a lease owns, in a stable order for the message."""
    return sorted(set(names) & RESERVED)


async def upsert_patch(
    room: str,
    key: str,
    meta: dict,
    content: str,
    patch: dict,
    handle: str,
    *,
    notify: bool = True,
) -> dict:
    """Merge ``patch`` into a memory's frontmatter and return the fresh half.

    The single writer behind both a board field write and a assignment lease, so
    the two cannot drift in how a frontmatter change reaches the store.  A
    ``None`` value clears its key, which is how a lease hands a row back.
    """
    from app.routes.memory import _reconstruct_value, upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    payload = MemoryBatchCreate(
        items=[
            MemoryCreate(
                key=key,
                value=_reconstruct_value(meta, content),
                content_text=content or None,
                # Frontmatter changed, prose did not: re-running the embedder
                # over unchanged text would burn a model call per row action. The
                # stored vector is carried forward instead.
                embed=False,
                created_by=handle,
                meta=patch,
            )
        ]
    )
    written = await upsert_memories(room, payload, notify=notify)
    return {**unmanaged_meta(meta), **patch, "version": written[0].version}


def _load(room: str, key: str) -> tuple[dict, str]:
    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        raise FieldError(f"no memory '{key}' in this room", status=404, key=key)
    return found


def read(room: str, key: str) -> dict:
    """A row's writable fields as they stand, without changing anything."""
    meta, _ = _load(room, key)
    return {"key": key, "fields": unmanaged_meta(meta), "version": meta.get("version")}


async def write(room: str, key: str, patch: dict, handle: str) -> dict:
    """Put ``patch`` on the row's frontmatter, refusing what a lease owns."""
    if not patch:
        raise FieldError("no fields to write", status=422, key=key)
    clashes = reserved_in(patch)
    if clashes:
        raise FieldError(RESERVED_REASON, status=422, key=key, reserved=clashes)
    meta, content = _load(room, key)
    fresh = await upsert_patch(room, key, meta, content, patch, handle)
    return {
        "key": key,
        "fields": {k: v for k, v in fresh.items() if k != "version"},
        "version": fresh.get("version"),
    }
