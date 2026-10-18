# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Which agents are paused, by whom and since when.

A pause stops an agent's turn and holds its wakes until it is resumed: messages
for it still land in the room, and the resume's wake hands it everything that
arrived (``room_channels.drain_herdr_wakes`` holds, ``wake_digest`` says it).
Only an agent's owner may pause, resume or stop it (``routes/agents``).

Kept in one JSON file in the data dir, ``pauses.json``, as
``{room: {handle: {by, at}}}``, so a hub restart doesn't quietly unpause anyone
overnight. Written beside itself and renamed over, so a reader never sees half
a file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.agent_registry import norm_handle
from app.services.filesystem import get_data_dir

logger = logging.getLogger(__name__)

FILENAME = "pauses.json"

_lock = threading.Lock()


def _path() -> Path:
    return get_data_dir() / FILENAME


def _load() -> dict[str, dict[str, dict[str, str]]]:
    try:
        data: Any = json.loads(_path().read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("unreadable %s; treating every agent as not paused", FILENAME)
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(room): {str(h): p for h, p in handles.items() if isinstance(p, dict)}
        for room, handles in data.items()
        if isinstance(handles, dict)
    }


def _save(data: dict[str, dict[str, dict[str, str]]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".pauses.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump({room: handles for room, handles in data.items() if handles}, fh, indent=2)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def get(room: str, handle: str) -> dict[str, str] | None:
    """``{by, at}`` for a paused agent, or ``None``."""
    return _load().get(room, {}).get(norm_handle(handle) or handle)


def is_paused(room: str, handle: str) -> bool:
    return get(room, handle) is not None


def paused_in(room: str) -> dict[str, dict[str, str]]:
    """Every paused agent in ``room``: handle → ``{by, at}``."""
    return dict(_load().get(room, {}))


def pause(room: str, handle: str, by: str) -> dict[str, str]:
    """Pause ``handle`` in ``room``. Pausing a paused agent keeps the first pause."""
    key = norm_handle(handle) or handle
    with _lock:
        data = _load()
        held = data.setdefault(room, {})
        if key not in held:
            held[key] = {"by": norm_handle(by) or by, "at": datetime.now(UTC).isoformat()}
            _save(data)
        return held[key]


def resume(room: str, handle: str) -> dict[str, str] | None:
    """End ``handle``'s pause; the pause it had, or ``None`` if it had none."""
    key = norm_handle(handle) or handle
    with _lock:
        data = _load()
        was = data.get(room, {}).pop(key, None)
        if was is not None:
            _save(data)
        return was


def rename(room: str, old: str, new: str) -> None:
    """Carry a pause to an agent's new handle."""
    with _lock:
        data = _load()
        held = data.get(room, {})
        if old in held:
            held[new] = held.pop(old)
            _save(data)


def forget_room(room: str) -> None:
    """Drop every pause in a room that was deleted."""
    with _lock:
        data = _load()
        if data.pop(room, None) is not None:
            _save(data)
