# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The ``mycelium-3.1-names`` migration: a room's stored messages and ids in
their current names.

A room recorded before 3.1 names its threads ``urn:ioc:mycelium:episode:...``
and its topic ``urn:concept:mycelium:...``, keeps each message's envelope under
the key ``l9``, and its headers name their format ``SSTP`` at version
``0.0.6``. This rewrites them, in every text file in the room's folder (its
transcript, its read positions, its rows' frontmatter, its episode records and
search index), to ``urn:mycelium:episode:...``, ``urn:mycelium:topic:...``, the
key ``envelope`` and ``MYCP`` ``1.0.0``, so an old thread and a new one are read
the same way.

Before a file is rewritten, it is copied as it was to
``<data dir>/backups/pre-3.1/<room>/<path>``. Each file is then rewritten whole
and swapped in, so a stopped run leaves every file either old or new, and the
next run picks up what is left.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from app.services import message_format, migrations

logger = logging.getLogger(__name__)

MIGRATION = "mycelium-3.1-names"

#: Where each room's files are copied before they are rewritten.
BACKUP_DIR = Path("backups") / "pre-3.1"

#: The files rewritten: everything the hub writes as text into a room's folder.
_TEXT_SUFFIXES = frozenset({".md", ".jsonl", ".json"})

#: The header fields of a recorded message, as ``json.dumps`` writes them.
_HEADER_REWRITES = {
    '"protocol": "SSTP"': f'"protocol": "{message_format.PROTOCOL}"',
    '"version": "0.0.6"': f'"version": "{message_format.VERSION}"',
}

#: The envelope's key in a recorded message, as ``json.dumps`` writes it. Not
#: after a backslash, so a message whose text quotes ``"l9": {`` keeps it.
_LEGACY_ENVELOPE_KEY = re.compile(r'(?<!\\)"l9": \{')


def rewrite_text(text: str, *, records: bool) -> str:
    """``text`` with every legacy URN prefix replaced, and with ``records``
    (a JSONL file of recorded messages) the envelope key, format and version
    too."""
    for old, new in message_format.LEGACY_URN_PREFIXES.items():
        text = text.replace(old, new)
    if records:
        text = _LEGACY_ENVELOPE_KEY.sub(f'"{message_format.CONTENT_ENVELOPE_KEY}": {{', text)
        for old, new in _HEADER_REWRITES.items():
            text = text.replace(old, new)
    return text


def _rewrite_file(path: Path, backup: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    new = rewrite_text(text, records=path.suffix == ".jsonl")
    if new == text:
        return False
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    tmp = path.with_name(f".{path.name}.migrating")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, path)
    return True


def migrate_room(room: str) -> migrations.Changed:
    """Rewrite ``room``'s folder, backing up each file first; what changed,
    for the ledger."""
    from app.services.filesystem import get_data_dir, room_path

    root = room_path(room)
    if not root.is_dir():
        return None
    backups = get_data_dir() / BACKUP_DIR / room
    changed = [
        str(path.relative_to(root))
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.suffix in _TEXT_SUFFIXES
        and _rewrite_file(path, backups / path.relative_to(root))
    ]
    return {"files": len(changed), "backup": str(backups)} if changed else None


migrations.register(
    migrations.Migration(
        id=MIGRATION,
        says="rewrote the room's ids and message envelopes to their 3.1 names",
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
            logger.exception("could not rewrite the names in room %s", room)
    return ran
