from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.coordination_session_read import CoordinationSessionRead
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    room_name: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/rooms/{room_name}/sessions/coordination".format(
            room_name=quote(str(room_name), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[CoordinationSessionRead] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = CoordinationSessionRead.from_dict(response_200_item_data)

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
) -> Response[HTTPValidationError | list[CoordinationSessionRead]]:
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
) -> Response[HTTPValidationError | list[CoordinationSessionRead]]:
    """List Coordination Sessions

     List negotiation sessions in a room.

    Returns first-class CoordinationSession entities scoped to ``room_name``.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[CoordinationSessionRead]]
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
) -> HTTPValidationError | list[CoordinationSessionRead] | None:
    """List Coordination Sessions

     List negotiation sessions in a room.

    Returns first-class CoordinationSession entities scoped to ``room_name``.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[CoordinationSessionRead]
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[HTTPValidationError | list[CoordinationSessionRead]]:
    """List Coordination Sessions

     List negotiation sessions in a room.

    Returns first-class CoordinationSession entities scoped to ``room_name``.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[CoordinationSessionRead]]
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
) -> HTTPValidationError | list[CoordinationSessionRead] | None:
    """List Coordination Sessions

     List negotiation sessions in a room.

    Returns first-class CoordinationSession entities scoped to ``room_name``.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[CoordinationSessionRead]
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
        )
    ).parsed
