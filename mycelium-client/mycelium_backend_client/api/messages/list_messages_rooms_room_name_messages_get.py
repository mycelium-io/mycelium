from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.message_list_response import MessageListResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    room_name: str,
    *,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    sender: None | str | Unset = UNSET,
    message_type: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params["offset"] = offset

    json_sender: None | str | Unset
    if isinstance(sender, Unset):
        json_sender = UNSET
    else:
        json_sender = sender
    params["sender"] = json_sender

    json_message_type: None | str | Unset
    if isinstance(message_type, Unset):
        json_message_type = UNSET
    else:
        json_message_type = message_type
    params["message_type"] = json_message_type

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/rooms/{room_name}/messages".format(
            room_name=quote(str(room_name), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | MessageListResponse | None:
    if response.status_code == 200:
        response_200 = MessageListResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | MessageListResponse]:
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
    offset: int | Unset = 0,
    sender: None | str | Unset = UNSET,
    message_type: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | MessageListResponse]:
    """List Messages

     List messages in a room, newest first.

    Args:
        room_name (str):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        sender (None | str | Unset):
        message_type (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MessageListResponse]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        limit=limit,
        offset=offset,
        sender=sender,
        message_type=message_type,
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
    offset: int | Unset = 0,
    sender: None | str | Unset = UNSET,
    message_type: None | str | Unset = UNSET,
) -> HTTPValidationError | MessageListResponse | None:
    """List Messages

     List messages in a room, newest first.

    Args:
        room_name (str):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        sender (None | str | Unset):
        message_type (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MessageListResponse
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
        limit=limit,
        offset=offset,
        sender=sender,
        message_type=message_type,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    sender: None | str | Unset = UNSET,
    message_type: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | MessageListResponse]:
    """List Messages

     List messages in a room, newest first.

    Args:
        room_name (str):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        sender (None | str | Unset):
        message_type (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MessageListResponse]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        limit=limit,
        offset=offset,
        sender=sender,
        message_type=message_type,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    sender: None | str | Unset = UNSET,
    message_type: None | str | Unset = UNSET,
) -> HTTPValidationError | MessageListResponse | None:
    """List Messages

     List messages in a room, newest first.

    Args:
        room_name (str):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        sender (None | str | Unset):
        message_type (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MessageListResponse
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
            limit=limit,
            offset=offset,
            sender=sender,
            message_type=message_type,
        )
    ).parsed
