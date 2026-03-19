from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    room_name: str,
    subscription_id: UUID,
) -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/rooms/{room_name}/memory/subscribe/{subscription_id}".format(
            room_name=quote(str(room_name), safe=""),
            subscription_id=quote(str(subscription_id), safe=""),
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
    subscription_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    """Unsubscribe

     Remove a memory subscription.

    Args:
        room_name (str):
        subscription_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        subscription_id=subscription_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    room_name: str,
    subscription_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    """Unsubscribe

     Remove a memory subscription.

    Args:
        room_name (str):
        subscription_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        room_name=room_name,
        subscription_id=subscription_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    subscription_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    """Unsubscribe

     Remove a memory subscription.

    Args:
        room_name (str):
        subscription_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        subscription_id=subscription_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    subscription_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    """Unsubscribe

     Remove a memory subscription.

    Args:
        room_name (str):
        subscription_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            subscription_id=subscription_id,
            client=client,
        )
    ).parsed
