# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Subagents on the hub: a handle of its own for an agent's subagent, so it
posts as itself, and ending it.

``mycelium subagent ...`` sends these. Each returns the hub's answer as plain
JSON, and a refusal raises :class:`~mycelium.exceptions.HubError`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.types import Response


def _body(resp: Response[Any]) -> Any:
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)
    return json.loads(resp.content) if resp.content else None


def start(client: Client, room: str, name: str, parent: str | None) -> dict[str, Any]:
    """Start ``parent``'s subagent ``name``: its handle, and its parent."""
    from mycelium_backend_client.api.subagents import (
        start_subagent_api_rooms_room_name_subagents_post as start_api,
    )
    from mycelium_backend_client.models import SubagentCreate

    body = SubagentCreate(name=name, parent=(parent or "").lstrip("@") or None)
    return _body(start_api.sync_detailed(room_name=room, client=client, body=body))


def end(client: Client, room: str, handle: str) -> dict[str, Any]:
    """End a subagent: it leaves the room's members, and its messages stay its own."""
    from mycelium_backend_client.api.subagents import (
        end_subagent_api_rooms_room_name_subagents_handle_delete as end_api,
    )

    return _body(end_api.sync_detailed(room_name=room, client=client, handle=handle.lstrip("@")))
