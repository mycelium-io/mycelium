# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A task on the hub: filing it, claiming, releasing or resolving it, writing
its fields, and reading one row or what the board is waiting on.

``mycelium board ...`` and :class:`mycelium.Room`'s ``board`` send these. Each
takes a generated client, so the CLI keeps its own session (and its own way of
saying a hub is down) and the library its own.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import (
        AssignmentRead,
        AssignmentWatchRead,
        BoardEpic,
        MemoryRead,
        WaitingRead,
    )


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


def renew_leases(client: Client, room: str, handle: str) -> list[str]:
    """Say ``handle`` is still here, for every row it holds; the keys renewed.

    A lease still in its first half is left alone, and the writes this does
    make broadcast nothing.
    """
    from mycelium.client import answered
    from mycelium_backend_client.api.assignments import (
        renew_assignments_api_rooms_room_name_assignments_renew_post as renew_api,
    )
    from mycelium_backend_client.models import AssignmentsRenewed, RenewBody

    resp = renew_api.sync_detailed(room, client=client, body=RenewBody(handle=handle))
    return [row.key for row in answered(resp, AssignmentsRenewed).renewed]


def watch_lease(
    client: Client, room: str, key: str, timeout: int, since: str | None = None
) -> AssignmentWatchRead:
    """One long-poll of up to ``timeout`` seconds on a row's lease: its state
    once it changes from ``since``, or as it stands when the wait is up."""
    from mycelium.client import answered
    from mycelium_backend_client.api.assignments import (
        await_assignment_api_rooms_room_name_assignments_await_get as watch_api,
    )
    from mycelium_backend_client.models import AssignmentWatchRead
    from mycelium_backend_client.types import UNSET

    resp = watch_api.sync_detailed(
        room, client=client, key=key, timeout=timeout, since=since if since is not None else UNSET
    )
    return answered(resp, AssignmentWatchRead)


def write_fields(client: Client, room: str, body: dict[str, Any]) -> None:
    """Write fields onto a row: ``key``, ``handle`` and ``fields``, and
    ``reassign`` to take it from whoever holds it (a 409 otherwise)."""
    from mycelium_backend_client.api.fields import write_fields_api_rooms_room_name_fields_post
    from mycelium_backend_client.models import WriteBody

    resp = write_fields_api_rooms_room_name_fields_post.sync_detailed(
        room, client=client, body=WriteBody.from_dict(body)
    )
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)


def read_row(client: Client, room: str, key: str) -> BoardEpic:
    """One row as the board draws it: its parts, where it stands, and the
    newest line said in its thread."""
    from mycelium.client import answered
    from mycelium_backend_client.api.board import read_board_row_api_rooms_room_name_board_key_get
    from mycelium_backend_client.models import BoardEpic

    resp = read_board_row_api_rooms_room_name_board_key_get.sync_detailed(room, key, client=client)
    return answered(resp, BoardEpic)


def waiting_on(client: Client, room: str, handle: str) -> WaitingRead:
    """What is waiting on ``handle``: asks to answer, its turn in a flow, its tasks."""
    from mycelium.client import answered
    from mycelium_backend_client.api.board import read_waiting_api_rooms_room_name_waiting_get
    from mycelium_backend_client.models import WaitingRead

    resp = read_waiting_api_rooms_room_name_waiting_get.sync_detailed(
        room, client=client, for_=handle
    )
    return answered(resp, WaitingRead)
