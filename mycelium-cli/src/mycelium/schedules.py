# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Schedules on the hub: an agent's recurring check-in, with a cheap pre-check
before it wakes, and its run history.

``mycelium schedule ...`` sends these. Each returns the hub's answer as plain
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


def create(client: Client, room: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Give an agent a schedule: ``name``, ``owner``, ``every`` or ``cron``,
    ``prompt``, and an optional ``check``, ``task`` and ``expires_in_days``."""
    from mycelium_backend_client.api.schedules import (
        create_schedule_api_rooms_room_name_schedules_post as create_api,
    )
    from mycelium_backend_client.models import ScheduleCreate

    body = ScheduleCreate(**fields)
    return _body(create_api.sync_detailed(room_name=room, client=client, body=body))


def list_schedules(client: Client, room: str, owner: str | None = None) -> dict[str, Any]:
    """The room's schedules, ``owner``'s alone when given."""
    from mycelium_backend_client.api.schedules import (
        list_schedules_api_rooms_room_name_schedules_get as list_api,
    )

    return _body(list_api.sync_detailed(room_name=room, client=client, owner=owner))


def get(client: Client, room: str, name: str) -> dict[str, Any]:
    """One schedule and its run history."""
    from mycelium_backend_client.api.schedules import (
        get_schedule_api_rooms_room_name_schedules_name_get as get_api,
    )

    return _body(get_api.sync_detailed(room_name=room, name=name, client=client))


def update(client: Client, room: str, name: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Change a schedule's fields; one left out (or ``None``) stays as it is."""
    from mycelium_backend_client.api.schedules import (
        update_schedule_api_rooms_room_name_schedules_name_patch as update_api,
    )
    from mycelium_backend_client.models import ScheduleUpdate

    body = ScheduleUpdate.from_dict({k: v for k, v in fields.items() if v is not None})
    return _body(update_api.sync_detailed(room_name=room, name=name, client=client, body=body))


def run(client: Client, room: str, name: str, *, wake: bool = False) -> dict[str, Any]:
    """Run a schedule now; ``wake`` skips its pre-check."""
    from mycelium_backend_client.api.schedules import (
        run_schedule_api_rooms_room_name_schedules_name_run_post as run_api,
    )
    from mycelium_backend_client.models import ScheduleRunRequest

    body = ScheduleRunRequest(wake=wake)
    return _body(run_api.sync_detailed(room_name=room, name=name, client=client, body=body))


def delete(client: Client, room: str, name: str) -> None:
    """Delete a schedule."""
    from mycelium_backend_client.api.schedules import (
        delete_schedule_api_rooms_room_name_schedules_name_delete as delete_api,
    )

    _body(delete_api.sync_detailed(room_name=room, name=name, client=client))
