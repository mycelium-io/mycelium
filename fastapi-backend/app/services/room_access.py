# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Who a room is listed for.

A room is shared (``is_public``, the default) or private. A private room has an
``owner`` and may name ``members``; it is listed, streamed and searched only
for them. Everyone else's room list, notification feed and search leave it out.

The viewer is the verified principal when the hub's sign-in is on, and
otherwise the handle the caller says it is (the browser's chosen name, the
CLI's identity), the same self-asserted identity the rest of the hub trusts
with the gate off.

The boundary, said plainly: this is about being *listed*. It keeps a private
room out of other people's way; it does not refuse a request for the room by
name. Anyone who knows the name can still open it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.agent_registry import norm_handle
from app.services.filesystem import list_room_names, read_room_meta

if TYPE_CHECKING:
    from fastapi import Request


def viewer_for(request: Request | None, claimed: str | None) -> str | None:
    """Who is asking: the verified principal if there is one, else the claim."""
    from app.services.actor import current_principal

    principal = current_principal(request)
    if principal is not None:
        return norm_handle(principal.handle)
    return norm_handle(claimed)


def visible_to(meta: dict[str, Any] | None, viewer: str | None) -> bool:
    """Whether a room with this metadata is listed for ``viewer``."""
    if not meta:
        return False
    if meta.get("is_public", True):
        return True
    if not viewer:
        return False
    allowed = {norm_handle(meta.get("owner"))} | {norm_handle(m) for m in meta.get("members") or []}
    return viewer in allowed - {None}


def visible_rooms(viewer: str | None) -> list[str]:
    """Every room listed for ``viewer``."""
    return [name for name in list_room_names() if visible_to(read_room_meta(name), viewer)]
