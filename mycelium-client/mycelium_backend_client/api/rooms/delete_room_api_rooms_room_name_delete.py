from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    room_name: str,
) -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/api/rooms/{room_name}".format(
            room_name=quote(str(room_name), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    r"""Delete Room

     Delete a room and cascade to its child session rooms.

    Cleanup order is important to avoid stale state firing against
    already-deleted rows:

      1. Enumerate child session rooms (``parent_namespace == room_name``).
      2. Tear down all in-memory CFN coordination state for the namespace
         and its children (cancels pending join timers and active round
         timeouts, posts ``coordination_consensus broken=True`` to any
         SSE subscribers).
      3. Delete child ``Session`` rows, then child ``Room`` rows.
      4. Mark any active child rooms as ``coordination_state=\"failed\"``
         (defensive — if step 3 didn't catch them due to a race, the
         state still reflects reality).
      5. Delete the parent ``Room`` row.
      6. Remove the filesystem directory.
      7. Delete the MAS in the CFN mgmt plane (non-fatal, last so a CFN
         error doesn't block the local cleanup).

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    r"""Delete Room

     Delete a room and cascade to its child session rooms.

    Cleanup order is important to avoid stale state firing against
    already-deleted rows:

      1. Enumerate child session rooms (``parent_namespace == room_name``).
      2. Tear down all in-memory CFN coordination state for the namespace
         and its children (cancels pending join timers and active round
         timeouts, posts ``coordination_consensus broken=True`` to any
         SSE subscribers).
      3. Delete child ``Session`` rows, then child ``Room`` rows.
      4. Mark any active child rooms as ``coordination_state=\"failed\"``
         (defensive — if step 3 didn't catch them due to a race, the
         state still reflects reality).
      5. Delete the parent ``Room`` row.
      6. Remove the filesystem directory.
      7. Delete the MAS in the CFN mgmt plane (non-fatal, last so a CFN
         error doesn't block the local cleanup).

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    r"""Delete Room

     Delete a room and cascade to its child session rooms.

    Cleanup order is important to avoid stale state firing against
    already-deleted rows:

      1. Enumerate child session rooms (``parent_namespace == room_name``).
      2. Tear down all in-memory CFN coordination state for the namespace
         and its children (cancels pending join timers and active round
         timeouts, posts ``coordination_consensus broken=True`` to any
         SSE subscribers).
      3. Delete child ``Session`` rows, then child ``Room`` rows.
      4. Mark any active child rooms as ``coordination_state=\"failed\"``
         (defensive — if step 3 didn't catch them due to a race, the
         state still reflects reality).
      5. Delete the parent ``Room`` row.
      6. Remove the filesystem directory.
      7. Delete the MAS in the CFN mgmt plane (non-fatal, last so a CFN
         error doesn't block the local cleanup).

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    r"""Delete Room

     Delete a room and cascade to its child session rooms.

    Cleanup order is important to avoid stale state firing against
    already-deleted rows:

      1. Enumerate child session rooms (``parent_namespace == room_name``).
      2. Tear down all in-memory CFN coordination state for the namespace
         and its children (cancels pending join timers and active round
         timeouts, posts ``coordination_consensus broken=True`` to any
         SSE subscribers).
      3. Delete child ``Session`` rows, then child ``Room`` rows.
      4. Mark any active child rooms as ``coordination_state=\"failed\"``
         (defensive — if step 3 didn't catch them due to a race, the
         state still reflects reality).
      5. Delete the parent ``Room`` row.
      6. Remove the filesystem directory.
      7. Delete the MAS in the CFN mgmt plane (non-fatal, last so a CFN
         error doesn't block the local cleanup).

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
        )
    ).parsed
