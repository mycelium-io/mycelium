from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    workspace_id: UUID,
    mas_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/shared-memories/query".format(
            workspace_id=quote(str(workspace_id), safe=""),
            mas_id=quote(str(mas_id), safe=""),
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
    workspace_id: UUID,
    mas_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    """Fetch Shared Memories

     Query shared memory graph directly from AgensGraph.

    Args:
        workspace_id (UUID):
        mas_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    workspace_id: UUID,
    mas_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    """Fetch Shared Memories

     Query shared memory graph directly from AgensGraph.

    Args:
        workspace_id (UUID):
        mas_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        workspace_id=workspace_id,
        mas_id=mas_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    workspace_id: UUID,
    mas_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    """Fetch Shared Memories

     Query shared memory graph directly from AgensGraph.

    Args:
        workspace_id (UUID):
        mas_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    workspace_id: UUID,
    mas_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    """Fetch Shared Memories

     Query shared memory graph directly from AgensGraph.

    Args:
        workspace_id (UUID):
        mas_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            client=client,
        )
    ).parsed
