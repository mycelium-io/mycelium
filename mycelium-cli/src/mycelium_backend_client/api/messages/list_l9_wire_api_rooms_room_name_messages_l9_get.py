from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_l9_wire_api_rooms_room_name_messages_l9_get_response_200_item import (
    ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    room_name: str,
    *,
    limit: int | Unset = 200,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/rooms/{room_name}/messages/l9".format(
            room_name=quote(str(room_name), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item.from_dict(
                response_200_item_data
            )

            response_200.append(response_200_item)

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item]]:
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
    limit: int | Unset = 200,
) -> Response[HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item]]:
    """List L9 Wire

     The room's L9 wire feed, replayed from the transcript (oldest first).

    Backfills the live L9 inspector: the SSE bus carries no history, so a freshly
    opened tab would otherwise start empty. Frames are the exact shape the bus
    pushes, so the client projects backfill and live frames identically.

    Args:
        room_name (str):
        limit (int | Unset):  Default: 200.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item]]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 200,
) -> HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item] | None:
    """List L9 Wire

     The room's L9 wire feed, replayed from the transcript (oldest first).

    Backfills the live L9 inspector: the SSE bus carries no history, so a freshly
    opened tab would otherwise start empty. Frames are the exact shape the bus
    pushes, so the client projects backfill and live frames identically.

    Args:
        room_name (str):
        limit (int | Unset):  Default: 200.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item]
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 200,
) -> Response[HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item]]:
    """List L9 Wire

     The room's L9 wire feed, replayed from the transcript (oldest first).

    Backfills the live L9 inspector: the SSE bus carries no history, so a freshly
    opened tab would otherwise start empty. Frames are the exact shape the bus
    pushes, so the client projects backfill and live frames identically.

    Args:
        room_name (str):
        limit (int | Unset):  Default: 200.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item]]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 200,
) -> HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item] | None:
    """List L9 Wire

     The room's L9 wire feed, replayed from the transcript (oldest first).

    Backfills the live L9 inspector: the SSE bus carries no history, so a freshly
    opened tab would otherwise start empty. Frames are the exact shape the bus
    pushes, so the client projects backfill and live frames identically.

    Args:
        room_name (str):
        limit (int | Unset):  Default: 200.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[ListL9WireApiRoomsRoomNameMessagesL9GetResponse200Item]
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
            limit=limit,
        )
    ).parsed
