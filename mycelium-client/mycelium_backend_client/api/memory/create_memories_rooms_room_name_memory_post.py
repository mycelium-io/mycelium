from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_batch_create import MemoryBatchCreate
from ...models.memory_read import MemoryRead
from ...types import Response


def _get_kwargs(
    room_name: str,
    *,
    body: MemoryBatchCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/rooms/{room_name}/memory".format(
            room_name=quote(str(room_name), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[MemoryRead] | None:
    if response.status_code == 201:
        response_201 = []
        _response_201 = response.json()
        for response_201_item_data in _response_201:
            response_201_item = MemoryRead.from_dict(response_201_item_data)

            response_201.append(response_201_item)

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
) -> Response[HTTPValidationError | list[MemoryRead]]:
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
    body: MemoryBatchCreate,
) -> Response[HTTPValidationError | list[MemoryRead]]:
    """Create Memories

     Create or upsert one or more memories (batch: 1-100 items).

    Writes markdown files to .mycelium/rooms/{room_name}/ and updates
    the pgvector search index.

    Args:
        room_name (str):
        body (MemoryBatchCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[MemoryRead]]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    body: MemoryBatchCreate,
) -> HTTPValidationError | list[MemoryRead] | None:
    """Create Memories

     Create or upsert one or more memories (batch: 1-100 items).

    Writes markdown files to .mycelium/rooms/{room_name}/ and updates
    the pgvector search index.

    Args:
        room_name (str):
        body (MemoryBatchCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[MemoryRead]
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    body: MemoryBatchCreate,
) -> Response[HTTPValidationError | list[MemoryRead]]:
    """Create Memories

     Create or upsert one or more memories (batch: 1-100 items).

    Writes markdown files to .mycelium/rooms/{room_name}/ and updates
    the pgvector search index.

    Args:
        room_name (str):
        body (MemoryBatchCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[MemoryRead]]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    body: MemoryBatchCreate,
) -> HTTPValidationError | list[MemoryRead] | None:
    """Create Memories

     Create or upsert one or more memories (batch: 1-100 items).

    Writes markdown files to .mycelium/rooms/{room_name}/ and updates
    the pgvector search index.

    Args:
        room_name (str):
        body (MemoryBatchCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[MemoryRead]
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
            body=body,
        )
    ).parsed
