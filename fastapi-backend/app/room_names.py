# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every request names a room the way the room was made.

A room's name ignores case (``filesystem.canonical_room_name``). This puts the
room's own spelling into the path of every ``/api/rooms/<name>/…`` request
before a route sees it, so the live channel, the stream, the transcript and
every key built from the name agree whichever spelling a caller typed. Without
it, on macOS and Windows, whose disks ignore case, ``marc`` and ``Marc`` were
one folder but two live channels, and a message sent to one never reached a
Channel open on the other.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.services.filesystem import canonical_room_name

_PREFIX = "/api/rooms/"


def canonical_path(path: str) -> str:
    """``path`` with its room name spelled as the room's, if it names one."""
    if not path.startswith(_PREFIX):
        return path
    name, sep, rest = path[len(_PREFIX) :].partition("/")
    if not name:
        return path
    spelled = canonical_room_name(name)
    return path if spelled == name else f"{_PREFIX}{spelled}{sep}{rest}"


class CanonicalRoomMiddleware:
    """ASGI middleware rewriting a request's room name to the room's spelling."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") in ("http", "websocket"):
            path = scope.get("path", "")
            fixed = canonical_path(path)
            if fixed != path:
                raw = scope.get("raw_path")
                scope = {**scope, "path": fixed}
                if raw is not None:
                    scope["raw_path"] = _raw(raw.decode("latin-1"), fixed).encode("latin-1")
        await self.app(scope, receive, send)


def _raw(raw: str, fixed: str) -> str:
    """The encoded path with its room name replaced, the rest left as sent."""
    _, sep, rest = raw[len(_PREFIX) :].partition("/")
    spelled = fixed[len(_PREFIX) :].partition("/")[0]
    return f"{_PREFIX}{quote(spelled, safe='')}{sep}{rest}"
