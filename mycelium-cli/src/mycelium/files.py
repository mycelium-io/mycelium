# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Adding a file to a room on the hub.

``mycelium file upload`` and :class:`mycelium.Room`'s ``files`` send this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from pathlib import Path


def upload_file(http: Any, room: str, path: Path, handle: str | None) -> dict[str, Any]:
    """Add one file to the room through a raw ``httpx`` client, and return its record."""
    with path.open("rb") as fh:
        resp = http.post(
            f"/api/rooms/{quote(room, safe='')}/uploads",
            files={"file": (path.name, fh, "application/octet-stream")},
            data={"created_by": handle or ""},
        )
    if resp.status_code != 201:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)
    return resp.json()
