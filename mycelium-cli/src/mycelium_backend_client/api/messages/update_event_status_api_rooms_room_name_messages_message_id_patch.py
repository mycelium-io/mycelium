from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.event_status_update import EventStatusUpdate
from ...models.http_validation_error import HTTPValidationError
from ...models.message_read import MessageRead
from ...types import Response


def _get_kwargs(
    room_name: str,
    message_id: UUID,
    *,
    body: EventStatusUpdate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/rooms/{room_name}/messages/{message_id}".format(
            room_name=quote(str(room_name), safe=""),
            message_id=quote(str(message_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | MessageRead | None:
    if response.status_code == 200:
        response_200 = MessageRead.from_dict(response.json())

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
) -> Response[HTTPValidationError | MessageRead]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    room_name: str,
    message_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EventStatusUpdate,
) -> Response[HTTPValidationError | MessageRead]:
    """Update Event Status

     Transition a stateful event's status (open -> in_progress -> resolved).

    Args:
        room_name (str):
        message_id (UUID):
        body (EventStatusUpdate): Body for PATCH /rooms/{name}/messages/{id} — transition an
            event's status.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MessageRead]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        message_id=message_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    room_name: str,
    message_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EventStatusUpdate,
) -> HTTPValidationError | MessageRead | None:
    """Update Event Status

     Transition a stateful event's status (open -> in_progress -> resolved).

    Args:
        room_name (str):
        message_id (UUID):
        body (EventStatusUpdate): Body for PATCH /rooms/{name}/messages/{id} — transition an
            event's status.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MessageRead
    """

    return sync_detailed(
        room_name=room_name,
        message_id=message_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    message_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EventStatusUpdate,
) -> Response[HTTPValidationError | MessageRead]:
    """Update Event Status

     Transition a stateful event's status (open -> in_progress -> resolved).

    Args:
        room_name (str):
        message_id (UUID):
        body (EventStatusUpdate): Body for PATCH /rooms/{name}/messages/{id} — transition an
            event's status.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MessageRead]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        message_id=message_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    message_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EventStatusUpdate,
) -> HTTPValidationError | MessageRead | None:
    """Update Event Status

     Transition a stateful event's status (open -> in_progress -> resolved).

    Args:
        room_name (str):
        message_id (UUID):
        body (EventStatusUpdate): Body for PATCH /rooms/{name}/messages/{id} — transition an
            event's status.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MessageRead
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            message_id=message_id,
            client=client,
            body=body,
        )
    ).parsed
