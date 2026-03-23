from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.spawn_session_rooms_room_name_sessions_spawn_post_response_spawn_session_rooms_room_name_sessions_spawn_post import (
    SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost,
)
from ...types import Response


def _get_kwargs(
    room_name: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/rooms/{room_name}/sessions/spawn".format(
            room_name=quote(str(room_name), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost
    | None
):
    if response.status_code == 201:
        response_201 = SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost.from_dict(
            response.json()
        )

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    HTTPValidationError
    | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost
]:
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
) -> Response[
    HTTPValidationError
    | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost
]:
    """Spawn Session

     Explicitly spawn a negotiation session within a namespace room.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost]
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
) -> (
    HTTPValidationError
    | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost
    | None
):
    """Spawn Session

     Explicitly spawn a negotiation session within a namespace room.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    HTTPValidationError
    | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost
]:
    """Spawn Session

     Explicitly spawn a negotiation session within a namespace room.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost]
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
) -> (
    HTTPValidationError
    | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost
    | None
):
    """Spawn Session

     Explicitly spawn a negotiation session within a namespace room.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SpawnSessionRoomsRoomNameSessionsSpawnPostResponseSpawnSessionRoomsRoomNameSessionsSpawnPost
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
        )
    ).parsed
