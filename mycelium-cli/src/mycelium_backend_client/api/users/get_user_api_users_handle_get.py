from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.user_read import UserRead
from ...types import Response


def _get_kwargs(
    handle: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/users/{handle}".format(
            handle=quote(str(handle), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | UserRead | None:
    if response.status_code == 200:
        response_200 = UserRead.from_dict(response.json())

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
) -> Response[HTTPValidationError | UserRead]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    handle: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[HTTPValidationError | UserRead]:
    """Get User

     One user record plus the agents they own.

    Args:
        handle (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | UserRead]
    """

    kwargs = _get_kwargs(
        handle=handle,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    handle: str,
    *,
    client: AuthenticatedClient | Client,
) -> HTTPValidationError | UserRead | None:
    """Get User

     One user record plus the agents they own.

    Args:
        handle (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | UserRead
    """

    return sync_detailed(
        handle=handle,
        client=client,
    ).parsed


async def asyncio_detailed(
    handle: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[HTTPValidationError | UserRead]:
    """Get User

     One user record plus the agents they own.

    Args:
        handle (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | UserRead]
    """

    kwargs = _get_kwargs(
        handle=handle,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    handle: str,
    *,
    client: AuthenticatedClient | Client,
) -> HTTPValidationError | UserRead | None:
    """Get User

     One user record plus the agents they own.

    Args:
        handle (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | UserRead
    """

    return (
        await asyncio_detailed(
            handle=handle,
            client=client,
        )
    ).parsed
