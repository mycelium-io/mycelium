from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.episode_list_response import EpisodeListResponse
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    room_name: str,
    *,
    limit: int | Unset = 50,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/rooms/{room_name}/episodes".format(
            room_name=quote(str(room_name), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EpisodeListResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = EpisodeListResponse.from_dict(response.json())

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
) -> Response[EpisodeListResponse | HTTPValidationError]:
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
    limit: int | Unset = 50,
) -> Response[EpisodeListResponse | HTTPValidationError]:
    """List Episodes

     List episode summaries for a room, newest first (an in-progress one first).

    Args:
        room_name (str):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EpisodeListResponse | HTTPValidationError]
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
    limit: int | Unset = 50,
) -> EpisodeListResponse | HTTPValidationError | None:
    """List Episodes

     List episode summaries for a room, newest first (an in-progress one first).

    Args:
        room_name (str):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EpisodeListResponse | HTTPValidationError
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
    limit: int | Unset = 50,
) -> Response[EpisodeListResponse | HTTPValidationError]:
    """List Episodes

     List episode summaries for a room, newest first (an in-progress one first).

    Args:
        room_name (str):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EpisodeListResponse | HTTPValidationError]
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
    limit: int | Unset = 50,
) -> EpisodeListResponse | HTTPValidationError | None:
    """List Episodes

     List episode summaries for a room, newest first (an in-progress one first).

    Args:
        room_name (str):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EpisodeListResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
            limit=limit,
        )
    ).parsed
