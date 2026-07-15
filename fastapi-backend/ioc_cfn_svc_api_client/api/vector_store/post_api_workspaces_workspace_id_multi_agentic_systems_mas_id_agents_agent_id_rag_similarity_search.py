from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_rag_similarity_search_response_400 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_rag_similarity_search_response_404 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_rag_similarity_search_response_500 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500,
)
from ...models.sharedmemory_vector_similarity_search_request import (
    SharedmemoryVectorSimilaritySearchRequest,
)
from ...models.sharedmemory_vector_similarity_search_response import (
    SharedmemoryVectorSimilaritySearchResponse,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    body: SharedmemoryVectorSimilaritySearchRequest,
    include_embeddings: bool | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    params: dict[str, Any] = {}

    params["include_embeddings"] = include_embeddings

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/agents/{agent_id}/rag/similarity-search".format(
            workspace_id=quote(str(workspace_id), safe=""),
            mas_id=quote(str(mas_id), safe=""),
            agent_id=quote(str(agent_id), safe=""),
        ),
        "params": params,
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500
    | SharedmemoryVectorSimilaritySearchResponse
    | None
):
    if response.status_code == 200:
        response_200 = SharedmemoryVectorSimilaritySearchResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400.from_dict(
            response.json()
        )

        return response_400

    if response.status_code == 404:
        response_404 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404.from_dict(
            response.json()
        )

        return response_404

    if response.status_code == 500:
        response_500 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500.from_dict(
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
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500
    | SharedmemoryVectorSimilaritySearchResponse
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
    body: SharedmemoryVectorSimilaritySearchRequest,
    include_embeddings: bool | Unset = UNSET,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500
    | SharedmemoryVectorSimilaritySearchResponse
]:
    """Similarity search scoped to an agent

     Performs vector similarity search over embeddings owned by a specific agent within a MAS store.

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        include_embeddings (bool | Unset):
        body (SharedmemoryVectorSimilaritySearchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500 | SharedmemoryVectorSimilaritySearchResponse]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        body=body,
        include_embeddings=include_embeddings,
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
    body: SharedmemoryVectorSimilaritySearchRequest,
    include_embeddings: bool | Unset = UNSET,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500
    | SharedmemoryVectorSimilaritySearchResponse
    | None
):
    """Similarity search scoped to an agent

     Performs vector similarity search over embeddings owned by a specific agent within a MAS store.

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        include_embeddings (bool | Unset):
        body (SharedmemoryVectorSimilaritySearchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500 | SharedmemoryVectorSimilaritySearchResponse
    """

    return sync_detailed(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        client=client,
        body=body,
        include_embeddings=include_embeddings,
    ).parsed


async def asyncio_detailed(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryVectorSimilaritySearchRequest,
    include_embeddings: bool | Unset = UNSET,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500
    | SharedmemoryVectorSimilaritySearchResponse
]:
    """Similarity search scoped to an agent

     Performs vector similarity search over embeddings owned by a specific agent within a MAS store.

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        include_embeddings (bool | Unset):
        body (SharedmemoryVectorSimilaritySearchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500 | SharedmemoryVectorSimilaritySearchResponse]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        body=body,
        include_embeddings=include_embeddings,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryVectorSimilaritySearchRequest,
    include_embeddings: bool | Unset = UNSET,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500
    | SharedmemoryVectorSimilaritySearchResponse
    | None
):
    """Similarity search scoped to an agent

     Performs vector similarity search over embeddings owned by a specific agent within a MAS store.

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        include_embeddings (bool | Unset):
        body (SharedmemoryVectorSimilaritySearchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdRagSimilaritySearchResponse500 | SharedmemoryVectorSimilaritySearchResponse
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            agent_id=agent_id,
            client=client,
            body=body,
            include_embeddings=include_embeddings,
        )
    ).parsed
