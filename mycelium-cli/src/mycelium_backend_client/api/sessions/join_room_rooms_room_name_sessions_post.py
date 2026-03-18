from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.session_create import SessionCreate
from ...models.session_read import SessionRead
from ...types import Response


def _get_kwargs(
    room_name: str,
    *,
    body: SessionCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/rooms/{room_name}/sessions".format(
            room_name=quote(str(room_name), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SessionRead | None:
    if response.status_code == 201:
        response_201 = SessionRead.from_dict(response.json())

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
) -> Response[HTTPValidationError | SessionRead]:
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
    body: SessionCreate,
) -> Response[HTTPValidationError | SessionRead]:
    """Join Room

     Register agent presence in a room (join). Creates room if it doesn't exist.

    Args:
        room_name (str):
        body (SessionCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SessionRead]
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
    body: SessionCreate,
) -> HTTPValidationError | SessionRead | None:
    """Join Room

     Register agent presence in a room (join). Creates room if it doesn't exist.

    Args:
        room_name (str):
        body (SessionCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SessionRead
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
    body: SessionCreate,
) -> Response[HTTPValidationError | SessionRead]:
    """Join Room

     Register agent presence in a room (join). Creates room if it doesn't exist.

    Args:
        room_name (str):
        body (SessionCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SessionRead]
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
    body: SessionCreate,
) -> HTTPValidationError | SessionRead | None:
    """Join Room

     Register agent presence in a room (join). Creates room if it doesn't exist.

    Args:
        room_name (str):
        body (SessionCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SessionRead
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
            body=body,
        )
    ).parsed
