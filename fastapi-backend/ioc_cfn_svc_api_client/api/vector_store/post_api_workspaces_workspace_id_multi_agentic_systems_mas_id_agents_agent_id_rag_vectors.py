from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_rag_vectors_response_201 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_rag_vectors_response_400 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_rag_vectors_response_404 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_rag_vectors_response_500 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500,
)
from ...models.sharedmemory_agent_vector_upsert_request import SharedmemoryAgentVectorUpsertRequest
from ...types import Response


def _get_kwargs(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    body: SharedmemoryAgentVectorUpsertRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/agents/{agent_id}/rag/vectors".format(
            workspace_id=quote(str(workspace_id), safe=""),
            mas_id=quote(str(mas_id), safe=""),
            agent_id=quote(str(agent_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500
    | None
):
    if response.status_code == 201:
        response_201 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201.from_dict(
            response.json()
        )

        return response_201

    if response.status_code == 400:
        response_400 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400.from_dict(
            response.json()
        )

        return response_400

    if response.status_code == 404:
        response_404 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404.from_dict(
            response.json()
        )

        return response_404

    if response.status_code == 500:
        response_500 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500.from_dict(
            response.json()
        )

        return response_500

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryAgentVectorUpsertRequest,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500
]:
    """Upsert vectors for an agent

     Upserts one or more vector records into the MAS store, tagged to a specific agent.

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        body (SharedmemoryAgentVectorUpsertRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryAgentVectorUpsertRequest,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500
    | None
):
    """Upsert vectors for an agent

     Upserts one or more vector records into the MAS store, tagged to a specific agent.

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        body (SharedmemoryAgentVectorUpsertRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500
    """

    return sync_detailed(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryAgentVectorUpsertRequest,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500
]:
    """Upsert vectors for an agent

     Upserts one or more vector records into the MAS store, tagged to a specific agent.

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        body (SharedmemoryAgentVectorUpsertRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryAgentVectorUpsertRequest,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500
    | None
):
    """Upsert vectors for an agent

     Upserts one or more vector records into the MAS store, tagged to a specific agent.

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        body (SharedmemoryAgentVectorUpsertRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse201 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagVectorsResponse500
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            agent_id=agent_id,
            client=client,
            body=body,
        )
    ).parsed
