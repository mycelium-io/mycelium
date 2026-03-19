from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.agent_create import AgentCreate
from ...models.agent_read import AgentRead
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    workspace_id: UUID,
    mas_id: UUID,
    *,
    body: AgentCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/mas/{mas_id}/agents".format(
            workspace_id=quote(str(workspace_id), safe=""),
            mas_id=quote(str(mas_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AgentRead | HTTPValidationError | None:
    if response.status_code == 201:
        response_201 = AgentRead.from_dict(response.json())

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
) -> Response[AgentRead | HTTPValidationError]:
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
    body: AgentCreate,
) -> Response[AgentRead | HTTPValidationError]:
    """Create Agent

    Args:
        workspace_id (UUID):
        mas_id (UUID):
        body (AgentCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AgentRead | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        body=body,
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
    body: AgentCreate,
) -> AgentRead | HTTPValidationError | None:
    """Create Agent

    Args:
        workspace_id (UUID):
        mas_id (UUID):
        body (AgentCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AgentRead | HTTPValidationError
    """

    return sync_detailed(
        workspace_id=workspace_id,
        mas_id=mas_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    workspace_id: UUID,
    mas_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: AgentCreate,
) -> Response[AgentRead | HTTPValidationError]:
    """Create Agent

    Args:
        workspace_id (UUID):
        mas_id (UUID):
        body (AgentCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AgentRead | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    workspace_id: UUID,
    mas_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: AgentCreate,
) -> AgentRead | HTTPValidationError | None:
    """Create Agent

    Args:
        workspace_id (UUID):
        mas_id (UUID):
        body (AgentCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AgentRead | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            client=client,
            body=body,
        )
    ).parsed
