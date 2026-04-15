from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    room_name: str,
    *,
    prefix: None | str | Unset = UNSET,
    scope: str | Unset = "namespace",
    handle: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    json_prefix: None | str | Unset
    if isinstance(prefix, Unset):
        json_prefix = UNSET
    else:
        json_prefix = prefix
    params["prefix"] = json_prefix

    params["scope"] = scope

    json_handle: None | str | Unset
    if isinstance(handle, Unset):
        json_handle = UNSET
    else:
        json_handle = handle
    params["handle"] = json_handle

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/rooms/{room_name}/memory".format(
            room_name=quote(str(room_name), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = response.json()
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
    prefix: None | str | Unset = UNSET,
    scope: str | Unset = "namespace",
    handle: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[Any | HTTPValidationError]:
    """List Memories

     List memories in a room.

    Reads from the filesystem, falls back to DB index.
    Supports ETag / If-None-Match for efficient sync — returns 304 if nothing changed.

    Args:
        room_name (str):
        prefix (None | str | Unset): Key prefix filter
        scope (str | Unset): Memory scope: namespace or notebook Default: 'namespace'.
        handle (None | str | Unset): Owner handle (required for notebook scope)
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        prefix=prefix,
        scope=scope,
        handle=handle,
        limit=limit,
        offset=offset,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    prefix: None | str | Unset = UNSET,
    scope: str | Unset = "namespace",
    handle: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Any | HTTPValidationError | None:
    """List Memories

     List memories in a room.

    Reads from the filesystem, falls back to DB index.
    Supports ETag / If-None-Match for efficient sync — returns 304 if nothing changed.

    Args:
        room_name (str):
        prefix (None | str | Unset): Key prefix filter
        scope (str | Unset): Memory scope: namespace or notebook Default: 'namespace'.
        handle (None | str | Unset): Owner handle (required for notebook scope)
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
        prefix=prefix,
        scope=scope,
        handle=handle,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    prefix: None | str | Unset = UNSET,
    scope: str | Unset = "namespace",
    handle: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[Any | HTTPValidationError]:
    """List Memories

     List memories in a room.

    Reads from the filesystem, falls back to DB index.
    Supports ETag / If-None-Match for efficient sync — returns 304 if nothing changed.

    Args:
        room_name (str):
        prefix (None | str | Unset): Key prefix filter
        scope (str | Unset): Memory scope: namespace or notebook Default: 'namespace'.
        handle (None | str | Unset): Owner handle (required for notebook scope)
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        prefix=prefix,
        scope=scope,
        handle=handle,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    prefix: None | str | Unset = UNSET,
    scope: str | Unset = "namespace",
    handle: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Any | HTTPValidationError | None:
    """List Memories

     List memories in a room.

    Reads from the filesystem, falls back to DB index.
    Supports ETag / If-None-Match for efficient sync — returns 304 if nothing changed.

    Args:
        room_name (str):
        prefix (None | str | Unset): Key prefix filter
        scope (str | Unset): Memory scope: namespace or notebook Default: 'namespace'.
        handle (None | str | Unset): Owner handle (required for notebook scope)
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

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
            prefix=prefix,
            scope=scope,
            handle=handle,
            limit=limit,
            offset=offset,
        )
    ).parsed
