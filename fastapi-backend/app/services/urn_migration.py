# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The ``mycelium-urns`` migration: a room's stored ids in their current form.

A room recorded before 3.1 names its threads ``urn:ioc:mycelium:episode:...``
and its topic ``urn:concept:mycelium:...``, and each recorded message's header
names its format ``SSTP`` at version ``0.0.6``. This rewrites them, in every
text file in the room's folder (its transcript, its read positions, its rows'
frontmatter, its episode records and search index), to
``urn:mycelium:episode:...``, ``urn:mycelium:topic:...`` and ``MYCP`` ``1.0.0``,
so an old thread and a new one are read the same way. Each file is rewritten
whole and swapped in, so a stopped run leaves every file either old or new,
and the next run picks up what is left.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.services import message_format, migrations

logger = logging.getLogger(__name__)

MIGRATION = "mycelium-urns"

#: The files rewritten: everything the hub writes as text into a room's folder.
_TEXT_SUFFIXES = frozenset({".md", ".jsonl", ".json"})

#: The header fields of a recorded message, as ``json.dumps`` writes them.
_HEADER_REWRITES = {
    '"protocol": "SSTP"': f'"protocol": "{message_format.PROTOCOL}"',
    '"version": "0.0.6"': f'"version": "{message_format.VERSION}"',
}


def rewrite_text(text: str, *, headers: bool) -> str:
    """``text`` with every legacy URN prefix replaced, and with ``headers`` the
    recorded messages' format and version too."""
    for old, new in message_format.LEGACY_URN_PREFIXES.items():
        text = text.replace(old, new)
    if headers:
        for old, new in _HEADER_REWRITES.items():
            text = text.replace(old, new)
    return text


def _rewrite_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    new = rewrite_text(text, headers=path.suffix == ".jsonl")
    if new == text:
        return False
    tmp = path.with_name(f".{path.name}.migrating")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, path)
    return True


def migrate_room(room: str) -> migrations.Changed:
    """Rewrite ``room``'s folder; what changed, for the ledger."""
    from app.services.filesystem import room_path

    root = room_path(room)
    if not root.is_dir():
        return None
    changed = [
        str(path.relative_to(root))
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in _TEXT_SUFFIXES and _rewrite_file(path)
    ]
    return {"files": len(changed)} if changed else None


migrations.register(
    migrations.Migration(
        id=MIGRATION,
        says="rewrote the room's thread and topic ids to urn:mycelium:",
        run=migrate_room,
    )
)


async def migrate_rooms(rooms: list[str]) -> int:
    """Run the migration for each of ``rooms`` that hasn't had it; how many ran."""
    ran = 0
    for room in rooms:
        try:
            ran += await migrations.once(MIGRATION, room)
        except Exception:
            logger.exception("could not rewrite the ids in room %s", room)
    return ran
