# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Which agents their owners keep running when agents are stopped in bulk.

``mycelium agent stop --idle`` and the Agents pane's quick picks leave a kept
agent out; stopping one by name still stops it. Kept in ``keeps.json`` in the
data dir, the same shape and the same way as ``pauses.json``:
``{room: {handle: {by, at}}}``.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from app.services.agent_registry import norm_handle
from app.services.pauses import _load, _save

FILENAME = "keeps.json"

_lock = threading.Lock()


def kept_in(room: str) -> dict[str, dict[str, str]]:
    """Every kept agent in ``room``: handle → ``{by, at}``."""
    return dict(_load(FILENAME).get(room, {}))


def is_kept(room: str, handle: str) -> bool:
    return (norm_handle(handle) or handle) in kept_in(room)


def keep(room: str, handle: str, by: str, *, on: bool = True) -> bool:
    """Keep ``handle`` running (``on``) or stop keeping it; whether it's kept now."""
    key = norm_handle(handle) or handle
    with _lock:
        data = _load(FILENAME)
        held = data.setdefault(room, {})
        if on and key not in held:
            held[key] = {"by": norm_handle(by) or by, "at": datetime.now(UTC).isoformat()}
            _save(data, FILENAME)
        elif not on and held.pop(key, None) is not None:
            _save(data, FILENAME)
        return key in held


def rename(room: str, old: str, new: str) -> None:
    """Carry a keep to an agent's new handle."""
    was, now = norm_handle(old) or old, norm_handle(new) or new
    with _lock:
        data = _load(FILENAME)
        held = data.get(room, {})
        if was in held:
            held[now] = held.pop(was)
            _save(data, FILENAME)


def forget_room(room: str) -> None:
    """Drop every keep in a room that was deleted."""
    with _lock:
        data = _load(FILENAME)
        if data.pop(room, None) is not None:
            _save(data, FILENAME)
