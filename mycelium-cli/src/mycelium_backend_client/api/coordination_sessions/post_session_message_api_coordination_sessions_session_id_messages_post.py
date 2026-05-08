from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.message_create import MessageCreate
from ...models.message_read import MessageRead
from ...types import Response


def _get_kwargs(
    session_id: UUID,
    *,
    body: MessageCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/coordination-sessions/{session_id}/messages".format(
            session_id=quote(str(session_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | MessageRead | None:
    if response.status_code == 201:
        response_201 = MessageRead.from_dict(response.json())

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
) -> Response[HTTPValidationError | MessageRead]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: MessageCreate,
) -> Response[HTTPValidationError | MessageRead]:
    """Post Session Message

     Post a message to a coordination session.

    Messages are stored with ``coordination_session_id`` set and ``room_name``
    null. SSE subscribers on the session-display channel still receive them
    via the same ``room:{display_name}`` NOTIFY topic during the deprecation
    window so existing OpenClaw plugin / CLI subscribers don't break.

    Args:
        session_id (UUID):
        body (MessageCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MessageRead]
    """

    kwargs = _get_kwargs(
        session_id=session_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: MessageCreate,
) -> HTTPValidationError | MessageRead | None:
    """Post Session Message

     Post a message to a coordination session.

    Messages are stored with ``coordination_session_id`` set and ``room_name``
    null. SSE subscribers on the session-display channel still receive them
    via the same ``room:{display_name}`` NOTIFY topic during the deprecation
    window so existing OpenClaw plugin / CLI subscribers don't break.

    Args:
        session_id (UUID):
        body (MessageCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MessageRead
    """

    return sync_detailed(
        session_id=session_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: MessageCreate,
) -> Response[HTTPValidationError | MessageRead]:
    """Post Session Message

     Post a message to a coordination session.

    Messages are stored with ``coordination_session_id`` set and ``room_name``
    null. SSE subscribers on the session-display channel still receive them
    via the same ``room:{display_name}`` NOTIFY topic during the deprecation
    window so existing OpenClaw plugin / CLI subscribers don't break.

    Args:
        session_id (UUID):
        body (MessageCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MessageRead]
    """

    kwargs = _get_kwargs(
        session_id=session_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: MessageCreate,
) -> HTTPValidationError | MessageRead | None:
    """Post Session Message

     Post a message to a coordination session.

    Messages are stored with ``coordination_session_id`` set and ``room_name``
    null. SSE subscribers on the session-display channel still receive them
    via the same ``room:{display_name}`` NOTIFY topic during the deprecation
    window so existing OpenClaw plugin / CLI subscribers don't break.

    Args:
        session_id (UUID):
        body (MessageCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MessageRead
    """

    return (
        await asyncio_detailed(
            session_id=session_id,
            client=client,
            body=body,
        )
    ).parsed
