# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Filing a task, and claiming, releasing or resolving it, on the hub.

``mycelium board new|claim|release|resolve`` and :class:`mycelium.Room`'s
``board`` send these. Each takes a generated client, so the CLI keeps its own
session (and its own way of saying a hub is down) and the library its own.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import AssignmentRead, MemoryRead


class Held(HubError):
    """A claim refused because someone else holds the row."""

    def __init__(self, key: str, owner: str | None, content: bytes) -> None:
        self.key = key
        self.owner = owner
        super().__init__(409, content)


class Waiting(HubError):
    """A claim refused because the row waits on rows not yet resolved."""

    def __init__(self, key: str, waiting_on: list[str], content: bytes) -> None:
        self.key = key
        self.waiting_on = waiting_on
        super().__init__(409, content)


def create_task(
    client: Client,
    room: str,
    *,
    title: str,
    handle: str,
    body: str | None = None,
    assign: str | None = None,
    parent: str | None = None,
) -> MemoryRead:
    """File a task on the board. ``parent`` is the memory key of the row it is part of."""
    from mycelium.client import answered
    from mycelium_backend_client.api.tasks import create_task_api_rooms_room_name_tasks_post
    from mycelium_backend_client.models import MemoryRead, TaskCreate

    fields: dict[str, Any] = {"title": title, "handle": handle}
    if body and body.strip():
        fields["content"] = body
    if assign:
        fields["assignee"] = assign.lstrip("@")
    if parent:
        fields["parent"] = parent
    resp = create_task_api_rooms_room_name_tasks_post.sync_detailed(
        room, client=client, body=TaskCreate.from_dict(fields)
    )
    return answered(resp, MemoryRead)


def change_assignment(client: Client, room: str, action: str, **fields: Any) -> AssignmentRead:
    """``claim``, ``release`` or ``resolve`` a row through its lease."""
    from mycelium.board.model import WAITING_FIELD
    from mycelium_backend_client.api.assignments import (
        claim_assignment_api_rooms_room_name_assignments_claim_post as claim_api,
    )
    from mycelium_backend_client.api.assignments import (
        release_assignment_api_rooms_room_name_assignments_release_post as release_api,
    )
    from mycelium_backend_client.api.assignments import (
        resolve_assignment_api_rooms_room_name_assignments_resolve_post as resolve_api,
    )
    from mycelium_backend_client.models import AssignmentRead, ClaimBody, ReleaseBody, ResolveBody

    payload = {k: v for k, v in fields.items() if v is not None}
    if action == "claim":
        resp = claim_api.sync_detailed(room, client=client, body=ClaimBody.from_dict(payload))
    elif action == "release":
        resp = release_api.sync_detailed(room, client=client, body=ReleaseBody.from_dict(payload))
    elif action == "resolve":
        resp = resolve_api.sync_detailed(room, client=client, body=ResolveBody.from_dict(payload))
    else:
        msg = f"unknown assignment action {action!r}"
        raise ValueError(msg)
    if resp.status_code == 409:  # noqa: PLR2004
        try:
            detail = json.loads(resp.content).get("detail", {})
        except (ValueError, AttributeError):
            detail = {}
        key = str(payload.get("key", ""))
        waiting = detail.get(WAITING_FIELD) if isinstance(detail, dict) else None
        if waiting:
            raise Waiting(key, [str(w) for w in waiting], resp.content)
        raise Held(key, detail.get("owner") if isinstance(detail, dict) else None, resp.content)
    if not isinstance(resp.parsed, AssignmentRead):
        raise HubError(resp.status_code, resp.content)
    return resp.parsed
