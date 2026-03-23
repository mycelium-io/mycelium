from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_operations_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_memory_operations_post_response_memory_operations_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_memory_operations_post import (
    MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost,
)
from ...types import Response


def _get_kwargs(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/agents/{agent_id}/memory-operations".format(
            workspace_id=quote(str(workspace_id), safe=""),
            mas_id=quote(str(mas_id), safe=""),
            agent_id=quote(str(agent_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost
    | None
):
    if response.status_code == 200:
        response_200 = MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost.from_dict(
            response.json()
        )

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
) -> Response[
    HTTPValidationError
    | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    HTTPValidationError
    | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost
]:
    r"""Memory Operations

     Proxy an arbitrary HTTP request to an agent's memory provider.

    Request envelope:
        {\"payload\": {\"http-request-type\": \"POST\", \"http-url\": \"/v1/memories\", \"http-request-
    body\": {...}, \"http-headers\": {...}}}

    Response envelope:
        {\"http-status\": 200, \"http-headers\": {...}, \"http-response-body\": {...}}

    Args:
        workspace_id (UUID):
        mas_id (UUID):
        agent_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> (
    HTTPValidationError
    | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost
    | None
):
    r"""Memory Operations

     Proxy an arbitrary HTTP request to an agent's memory provider.

    Request envelope:
        {\"payload\": {\"http-request-type\": \"POST\", \"http-url\": \"/v1/memories\", \"http-request-
    body\": {...}, \"http-headers\": {...}}}

    Response envelope:
        {\"http-status\": 200, \"http-headers\": {...}, \"http-response-body\": {...}}

    Args:
        workspace_id (UUID):
        mas_id (UUID):
        agent_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost
    """

    return sync_detailed(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    HTTPValidationError
    | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost
]:
    r"""Memory Operations

     Proxy an arbitrary HTTP request to an agent's memory provider.

    Request envelope:
        {\"payload\": {\"http-request-type\": \"POST\", \"http-url\": \"/v1/memories\", \"http-request-
    body\": {...}, \"http-headers\": {...}}}

    Response envelope:
        {\"http-status\": 200, \"http-headers\": {...}, \"http-response-body\": {...}}

    Args:
        workspace_id (UUID):
        mas_id (UUID):
        agent_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> (
    HTTPValidationError
    | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost
    | None
):
    r"""Memory Operations

     Proxy an arbitrary HTTP request to an agent's memory provider.

    Request envelope:
        {\"payload\": {\"http-request-type\": \"POST\", \"http-url\": \"/v1/memories\", \"http-request-
    body\": {...}, \"http-headers\": {...}}}

    Response envelope:
        {\"http-status\": 200, \"http-headers\": {...}, \"http-response-body\": {...}}

    Args:
        workspace_id (UUID):
        mas_id (UUID):
        agent_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPostResponseMemoryOperationsApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsPost
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            agent_id=agent_id,
            client=client,
        )
    ).parsed
