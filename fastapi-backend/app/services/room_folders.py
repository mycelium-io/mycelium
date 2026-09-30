# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A person's folders for their rooms list.

A preference, not an identity field, so it lives beside the user store rather
than in it (``contracts/user-store.json`` freezes the user record the CLI
mirrors): one JSON file per handle at ``preferences/<handle>/room-folders.json``
in the data dir. Rooms know nothing about it; two people can file the same room
in different folders, or in none.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.schemas import HANDLE_PATTERN, RoomFolders
from app.services.agent_registry import norm_handle
from app.services.filesystem import get_data_dir

logger = logging.getLogger(__name__)

FILENAME = "room-folders.json"


def _key(handle: str) -> str | None:
    """The normalized handle, or None when it isn't one a path can be made from."""
    key = norm_handle(handle)
    return key if key and re.fullmatch(HANDLE_PATTERN, key) else None


def _path(handle: str) -> Path:
    return get_data_dir() / "preferences" / handle / FILENAME


def normalize(layout: RoomFolders) -> RoomFolders:
    """File each room once, in the first folder that names it, and trim names.

    The client sends the whole layout, so a room dragged between two folders in
    a racing pair of writes can't end up in both.
    """
    seen: set[str] = set()
    folders = []
    for folder in layout.folders:
        rooms = []
        for room in folder.rooms:
            if room and room not in seen:
                seen.add(room)
                rooms.append(room)
        folders.append(
            folder.model_copy(update={"name": folder.name.strip() or "Folder", "rooms": rooms})
        )
    return RoomFolders(folders=folders)


def load(handle: str) -> RoomFolders:
    """The handle's folders, or none. A file that won't parse reads as none."""
    key = _key(handle)
    if not key:
        return RoomFolders()
    path = _path(key)
    try:
        data: Any = json.loads(path.read_text())
        return RoomFolders.model_validate(data)
    except FileNotFoundError:
        return RoomFolders()
    except (OSError, ValueError):
        logger.warning("unreadable room folders for %s; treating as none", key)
        return RoomFolders()


def save(handle: str, layout: RoomFolders) -> RoomFolders:
    """Replace the handle's folders, atomically, and return what was stored."""
    key = _key(handle)
    if not key:
        msg = f"not a handle: {handle!r}"
        raise ValueError(msg)
    stored = normalize(layout)
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and renamed over it, so a reader never sees half a file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".room-folders.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(stored.model_dump(), fh, indent=2)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return stored
