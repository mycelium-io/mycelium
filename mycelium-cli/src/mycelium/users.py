# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""People on the hub: the global user store, which spans rooms.

``mycelium user ...``, ``iam`` and ``whoami`` send these. A refusal raises
:class:`~mycelium.exceptions.HubError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import UserListResponse, UserRead


def get_user(client: Client, handle: str) -> UserRead | None:
    """The hub's record for ``handle``, with the agents they own; ``None``
    when the hub has no such user."""
    from mycelium.client import answered
    from mycelium_backend_client.api.users import get_user_api_users_handle_get as get_api
    from mycelium_backend_client.models import UserRead

    try:
        return answered(get_api.sync_detailed(handle=handle, client=client), UserRead)
    except HubError as exc:
        if exc.status_code == 404:  # noqa: PLR2004
            return None
        raise


def list_users(client: Client) -> UserListResponse:
    """Every user registered on the hub."""
    from mycelium.client import answered
    from mycelium_backend_client.api.users import list_users_api_users_get as list_api
    from mycelium_backend_client.models import UserListResponse

    return answered(list_api.sync_detailed(client=client), UserListResponse)


def save_user(
    client: Client,
    *,
    handle: str,
    display_name: str,
    teams: list[str],
    notify: str | None,
    created_by: str,
) -> UserRead:
    """Create or update a user record. Saving an unchanged record changes nothing."""
    from mycelium.client import answered
    from mycelium_backend_client.api.users import create_user_api_users_post as create_api
    from mycelium_backend_client.models import UserCreate, UserRead

    body = UserCreate(
        handle=handle,
        display_name=display_name,
        teams=teams,
        notify=notify,
        created_by=created_by,
    )
    return answered(create_api.sync_detailed(client=client, body=body), UserRead)
