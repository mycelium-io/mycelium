from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.subscription_read import SubscriptionRead
from ...types import Response


def _get_kwargs(
    room_name: str,
) -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/rooms/{room_name}/memory/subscriptions".format(
            room_name=quote(str(room_name), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[SubscriptionRead] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = SubscriptionRead.from_dict(response_200_item_data)

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
) -> Response[HTTPValidationError | list[SubscriptionRead]]:
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
) -> Response[HTTPValidationError | list[SubscriptionRead]]:
    """List Subscriptions

     List active memory subscriptions for a room.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[SubscriptionRead]]
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
) -> HTTPValidationError | list[SubscriptionRead] | None:
    """List Subscriptions

     List active memory subscriptions for a room.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[SubscriptionRead]
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[HTTPValidationError | list[SubscriptionRead]]:
    """List Subscriptions

     List active memory subscriptions for a room.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[SubscriptionRead]]
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
) -> HTTPValidationError | list[SubscriptionRead] | None:
    """List Subscriptions

     List active memory subscriptions for a room.

    Args:
        room_name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[SubscriptionRead]
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
        )
    ).parsed
