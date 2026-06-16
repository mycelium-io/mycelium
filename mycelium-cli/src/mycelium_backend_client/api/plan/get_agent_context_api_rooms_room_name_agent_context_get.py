from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.agent_context_out import AgentContextOut
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    room_name: str,
    *,
    handle: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_handle: None | str | Unset
    if isinstance(handle, Unset):
        json_handle = UNSET
    else:
        json_handle = handle
    params["handle"] = json_handle

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/rooms/{room_name}/agent-context".format(
            room_name=quote(str(room_name), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AgentContextOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = AgentContextOut.from_dict(response.json())

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
) -> Response[AgentContextOut | HTTPValidationError]:
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
    handle: None | str | Unset = UNSET,
) -> Response[AgentContextOut | HTTPValidationError]:
    """Get Agent Context

     Compact room briefing injected into an agent's prompt on dispatch.

    Hot path — called on every ``@handle`` dispatch — so it stays a pure
    filesystem read with no DB round-trip. ``handle`` is accepted now and
    reserved for per-agent data (claimed tasks) once that lands; v1 ignores
    it and returns the room-wide plan briefing.

    Args:
        room_name (str):
        handle (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AgentContextOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        handle=handle,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    handle: None | str | Unset = UNSET,
) -> AgentContextOut | HTTPValidationError | None:
    """Get Agent Context

     Compact room briefing injected into an agent's prompt on dispatch.

    Hot path — called on every ``@handle`` dispatch — so it stays a pure
    filesystem read with no DB round-trip. ``handle`` is accepted now and
    reserved for per-agent data (claimed tasks) once that lands; v1 ignores
    it and returns the room-wide plan briefing.

    Args:
        room_name (str):
        handle (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AgentContextOut | HTTPValidationError
    """

    return sync_detailed(
        room_name=room_name,
        client=client,
        handle=handle,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    handle: None | str | Unset = UNSET,
) -> Response[AgentContextOut | HTTPValidationError]:
    """Get Agent Context

     Compact room briefing injected into an agent's prompt on dispatch.

    Hot path — called on every ``@handle`` dispatch — so it stays a pure
    filesystem read with no DB round-trip. ``handle`` is accepted now and
    reserved for per-agent data (claimed tasks) once that lands; v1 ignores
    it and returns the room-wide plan briefing.

    Args:
        room_name (str):
        handle (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AgentContextOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        handle=handle,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    *,
    client: AuthenticatedClient | Client,
    handle: None | str | Unset = UNSET,
) -> AgentContextOut | HTTPValidationError | None:
    """Get Agent Context

     Compact room briefing injected into an agent's prompt on dispatch.

    Hot path — called on every ``@handle`` dispatch — so it stays a pure
    filesystem read with no DB round-trip. ``handle`` is accepted now and
    reserved for per-agent data (claimed tasks) once that lands; v1 ignores
    it and returns the room-wide plan briefing.

    Args:
        room_name (str):
        handle (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AgentContextOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            client=client,
            handle=handle,
        )
    ).parsed
