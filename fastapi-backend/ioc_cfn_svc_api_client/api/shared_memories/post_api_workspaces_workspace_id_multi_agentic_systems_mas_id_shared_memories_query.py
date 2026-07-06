from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_shared_memories_query_response_400 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_shared_memories_query_response_500 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500,
)
from ...models.sharedmemory_query_request import SharedmemoryQueryRequest
from ...models.sharedmemory_query_response import SharedmemoryQueryResponse
from ...types import Response


def _get_kwargs(
    workspace_id: str,
    mas_id: str,
    *,
    body: SharedmemoryQueryRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/shared-memories/query".format(
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
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500
    | SharedmemoryQueryResponse
    | None
):
    if response.status_code == 200:
        response_200 = SharedmemoryQueryResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400.from_dict(
            response.json()
        )

        return response_400

    if response.status_code == 500:
        response_500 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500.from_dict(
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
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500
    | SharedmemoryQueryResponse
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
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryQueryRequest,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500
    | SharedmemoryQueryResponse
]:
    """Fetch shared memories

     Queries shared memories for a given workspace and multi-agentic system using a graph path query.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SharedmemoryQueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500 | SharedmemoryQueryResponse]
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
    workspace_id: str,
    mas_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryQueryRequest,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500
    | SharedmemoryQueryResponse
    | None
):
    """Fetch shared memories

     Queries shared memories for a given workspace and multi-agentic system using a graph path query.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SharedmemoryQueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500 | SharedmemoryQueryResponse
    """

    return sync_detailed(
        workspace_id=workspace_id,
        mas_id=mas_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    workspace_id: str,
    mas_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryQueryRequest,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500
    | SharedmemoryQueryResponse
]:
    """Fetch shared memories

     Queries shared memories for a given workspace and multi-agentic system using a graph path query.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SharedmemoryQueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500 | SharedmemoryQueryResponse]
    """

    kwargs = _get_kwargs(
        workspace_id=workspace_id,
        mas_id=mas_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    workspace_id: str,
    mas_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: SharedmemoryQueryRequest,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500
    | SharedmemoryQueryResponse
    | None
):
    """Fetch shared memories

     Queries shared memories for a given workspace and multi-agentic system using a graph path query.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SharedmemoryQueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesQueryResponse500 | SharedmemoryQueryResponse
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            client=client,
            body=body,
        )
    ).parsed
