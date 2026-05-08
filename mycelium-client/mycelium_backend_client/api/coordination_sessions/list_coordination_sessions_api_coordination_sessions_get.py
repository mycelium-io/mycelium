from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.coordination_session_read import CoordinationSessionRead
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    parent_room: None | str | Unset = UNSET,
    state: None | str | Unset = UNSET,
    limit: int | Unset = 200,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    json_parent_room: None | str | Unset
    if isinstance(parent_room, Unset):
        json_parent_room = UNSET
    else:
        json_parent_room = parent_room
    params["parent_room"] = json_parent_room

    json_state: None | str | Unset
    if isinstance(state, Unset):
        json_state = UNSET
    else:
        json_state = state
    params["state"] = json_state

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/coordination-sessions",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[CoordinationSessionRead] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = CoordinationSessionRead.from_dict(response_200_item_data)

            response_200.append(response_200_item)

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
) -> Response[HTTPValidationError | list[CoordinationSessionRead]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    parent_room: None | str | Unset = UNSET,
    state: None | str | Unset = UNSET,
    limit: int | Unset = 200,
) -> Response[HTTPValidationError | list[CoordinationSessionRead]]:
    """List Coordination Sessions

     List coordination sessions, newest first.

    Supports two filters used by the OpenClaw channel plugin's polling loop
    (``state=waiting,negotiating``) and the frontend sessions rail
    (``parent_room=<name>``).

    Args:
        parent_room (None | str | Unset): Filter by parent room name
        state (None | str | Unset): Comma-separated state filter (e.g. 'waiting,negotiating')
        limit (int | Unset):  Default: 200.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[CoordinationSessionRead]]
    """

    kwargs = _get_kwargs(
        parent_room=parent_room,
        state=state,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    parent_room: None | str | Unset = UNSET,
    state: None | str | Unset = UNSET,
    limit: int | Unset = 200,
) -> HTTPValidationError | list[CoordinationSessionRead] | None:
    """List Coordination Sessions

     List coordination sessions, newest first.

    Supports two filters used by the OpenClaw channel plugin's polling loop
    (``state=waiting,negotiating``) and the frontend sessions rail
    (``parent_room=<name>``).

    Args:
        parent_room (None | str | Unset): Filter by parent room name
        state (None | str | Unset): Comma-separated state filter (e.g. 'waiting,negotiating')
        limit (int | Unset):  Default: 200.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[CoordinationSessionRead]
    """

    return sync_detailed(
        client=client,
        parent_room=parent_room,
        state=state,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    parent_room: None | str | Unset = UNSET,
    state: None | str | Unset = UNSET,
    limit: int | Unset = 200,
) -> Response[HTTPValidationError | list[CoordinationSessionRead]]:
    """List Coordination Sessions

     List coordination sessions, newest first.

    Supports two filters used by the OpenClaw channel plugin's polling loop
    (``state=waiting,negotiating``) and the frontend sessions rail
    (``parent_room=<name>``).

    Args:
        parent_room (None | str | Unset): Filter by parent room name
        state (None | str | Unset): Comma-separated state filter (e.g. 'waiting,negotiating')
        limit (int | Unset):  Default: 200.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[CoordinationSessionRead]]
    """

    kwargs = _get_kwargs(
        parent_room=parent_room,
        state=state,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    parent_room: None | str | Unset = UNSET,
    state: None | str | Unset = UNSET,
    limit: int | Unset = 200,
) -> HTTPValidationError | list[CoordinationSessionRead] | None:
    """List Coordination Sessions

     List coordination sessions, newest first.

    Supports two filters used by the OpenClaw channel plugin's polling loop
    (``state=waiting,negotiating``) and the frontend sessions rail
    (``parent_room=<name>``).

    Args:
        parent_room (None | str | Unset): Filter by parent room name
        state (None | str | Unset): Comma-separated state filter (e.g. 'waiting,negotiating')
        limit (int | Unset):  Default: 200.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[CoordinationSessionRead]
    """

    return (
        await asyncio_detailed(
            client=client,
            parent_room=parent_room,
            state=state,
            limit=limit,
        )
    ).parsed
