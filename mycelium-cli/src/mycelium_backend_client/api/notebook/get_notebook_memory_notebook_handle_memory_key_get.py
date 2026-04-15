from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_read import MemoryRead
from ...types import Response


def _get_kwargs(
    handle: str,
    key: str,
) -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/notebook/{handle}/memory/{key}".format(
            handle=quote(str(handle), safe=""),
            key=quote(str(key), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | MemoryRead | None:
    if response.status_code == 200:
        response_200 = MemoryRead.from_dict(response.json())

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
) -> Response[HTTPValidationError | MemoryRead]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    handle: str,
    key: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[HTTPValidationError | MemoryRead]:
    """Get Notebook Memory

     Get a specific notebook memory by key. Reads from filesystem first.

    Args:
        handle (str):
        key (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryRead]
    """

    kwargs = _get_kwargs(
        handle=handle,
        key=key,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    handle: str,
    key: str,
    *,
    client: AuthenticatedClient | Client,
) -> HTTPValidationError | MemoryRead | None:
    """Get Notebook Memory

     Get a specific notebook memory by key. Reads from filesystem first.

    Args:
        handle (str):
        key (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryRead
    """

    return sync_detailed(
        handle=handle,
        key=key,
        client=client,
    ).parsed


async def asyncio_detailed(
    handle: str,
    key: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[HTTPValidationError | MemoryRead]:
    """Get Notebook Memory

     Get a specific notebook memory by key. Reads from filesystem first.

    Args:
        handle (str):
        key (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryRead]
    """

    kwargs = _get_kwargs(
        handle=handle,
        key=key,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    handle: str,
    key: str,
    *,
    client: AuthenticatedClient | Client,
) -> HTTPValidationError | MemoryRead | None:
    """Get Notebook Memory

     Get a specific notebook memory by key. Reads from filesystem first.

    Args:
        handle (str):
        key (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryRead
    """

    return (
        await asyncio_detailed(
            handle=handle,
            key=key,
            client=client,
        )
    ).parsed
