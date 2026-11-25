# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Wake subscriptions on the hub: what wakes an agent besides a mention (a
task, its parts, a key pattern), for how long, and dropping them.

``mycelium subscribe ...`` and ``mycelium whoami`` send these. Each returns the
hub's answer as plain JSON, and a refusal raises
:class:`~mycelium.exceptions.HubError`.
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


def subscribe(
    client: Client,
    room: str,
    *,
    handle: str,
    kind: str,
    target: str,
    parts: bool = False,
    task: str | None = None,
    span: str | None = None,
) -> dict[str, Any]:
    """Wake ``handle`` on ``target`` (a ``kind``: task, pattern, ...) until ``span`` ends."""
    from mycelium_backend_client.api.subscriptions import (
        subscribe_api_rooms_room_name_subscriptions_post as subscribe_api,
    )
    from mycelium_backend_client.models import WakeSubscriptionCreate, WakeSubscriptionCreateKind

    body = WakeSubscriptionCreate(
        handle=handle.lstrip("@"),
        kind=WakeSubscriptionCreateKind(kind),
        target=target,
        parts=parts,
        task=task,
        span=span,
    )
    return _body(subscribe_api.sync_detailed(room_name=room, client=client, body=body))


def list_subscriptions(client: Client, room: str, handle: str | None) -> dict[str, Any]:
    """The room's subscriptions, ``handle``'s alone when given."""
    from mycelium_backend_client.api.subscriptions import (
        list_subscriptions_api_rooms_room_name_subscriptions_get as list_api,
    )

    return _body(list_api.sync_detailed(room_name=room, client=client, handle=handle))


def unsubscribe(client: Client, room: str, handle: str, sub_id: str | None) -> dict[str, Any]:
    """Drop one of ``handle``'s subscriptions, or every one when ``sub_id`` is None."""
    from mycelium_backend_client.api.subscriptions import (
        unsubscribe_api_rooms_room_name_subscriptions_delete as delete_api,
    )

    return _body(delete_api.sync_detailed(room_name=room, client=client, handle=handle, id=sub_id))
