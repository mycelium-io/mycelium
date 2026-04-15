from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    handle: str,
) -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/agents/{handle}/stream".format(
            handle=quote(str(handle), safe=""),
        ),
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
    handle: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    """Stream Agent Events

     Server-Sent Events stream for a specific agent handle.

    Delivers coordination_tick and coordination_consensus events addressed to
    this agent across all rooms — no room configuration required on the client.
    Connect with: curl -N http://localhost:8000/agents/{handle}/stream

    Args:
        handle (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        handle=handle,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    handle: str,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    """Stream Agent Events

     Server-Sent Events stream for a specific agent handle.

    Delivers coordination_tick and coordination_consensus events addressed to
    this agent across all rooms — no room configuration required on the client.
    Connect with: curl -N http://localhost:8000/agents/{handle}/stream

    Args:
        handle (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        handle=handle,
        client=client,
    ).parsed


async def asyncio_detailed(
    handle: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    """Stream Agent Events

     Server-Sent Events stream for a specific agent handle.

    Delivers coordination_tick and coordination_consensus events addressed to
    this agent across all rooms — no room configuration required on the client.
    Connect with: curl -N http://localhost:8000/agents/{handle}/stream

    Args:
        handle (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        handle=handle,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    handle: str,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    """Stream Agent Events

     Server-Sent Events stream for a specific agent handle.

    Delivers coordination_tick and coordination_consensus events addressed to
    this agent across all rooms — no room configuration required on the client.
    Connect with: curl -N http://localhost:8000/agents/{handle}/stream

    Args:
        handle (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            handle=handle,
            client=client,
        )
    ).parsed
