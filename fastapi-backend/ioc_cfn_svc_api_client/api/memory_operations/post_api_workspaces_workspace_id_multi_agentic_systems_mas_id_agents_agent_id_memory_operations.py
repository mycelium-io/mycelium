from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.memoryoperations_memory_operation_request import (
    MemoryoperationsMemoryOperationRequest,
)
from ...models.memoryoperations_memory_operation_response import (
    MemoryoperationsMemoryOperationResponse,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_memory_operations_response_400 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_memory_operations_response_404 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_memory_operations_response_502 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_agents_agent_id_memory_operations_response_503 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503,
)
from ...types import Response


def _get_kwargs(
    workspace_id: str,
    mas_id: str,
    agent_id: str,
    *,
    body: MemoryoperationsMemoryOperationRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/agents/{agent_id}/memory-operations".format(
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
    MemoryoperationsMemoryOperationResponse
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503
    | None
):
    if response.status_code == 200:
        response_200 = MemoryoperationsMemoryOperationResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400.from_dict(
            response.json()
        )

        return response_400

    if response.status_code == 404:
        response_404 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404.from_dict(
            response.json()
        )

        return response_404

    if response.status_code == 502:
        response_502 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502.from_dict(
            response.json()
        )

        return response_502

    if response.status_code == 503:
        response_503 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503.from_dict(
            response.json()
        )

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    MemoryoperationsMemoryOperationResponse
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503
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
    body: MemoryoperationsMemoryOperationRequest,
) -> Response[
    MemoryoperationsMemoryOperationResponse
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503
]:
    r"""Proxy API requests to a remote memory provider

     Forwards REST API requests to a remote memory provider (Mem0, Graphiti, etc.) for agent-specific
    memory operations.
    The memory provider base URL and auth credentials are auto-resolved from management plane config
    based on workspace/MAS/agent IDs.
    The `http-url` field should contain the relative path and query parameters to append to the provider
    base URL.

    **GET example** — retrieve memories:
    ```json
    {
    \"header\": {},
    \"payload\": {
    \"http-request-type\": \"GET\",
    \"http-url\": \"v1/memories/?user_id=curl-test-user\",
    \"http-request-body\": {},
    \"http-headers\": {}
    }
    }
    ```

    **POST example** — add memories:
    ```json
    {
    \"header\": {},
    \"payload\": {
    \"http-request-type\": \"POST\",
    \"http-url\": \"/v1/memories/\",
    \"http-request-body\": {
    \"messages\": [{\"role\": \"user\", \"content\": \"I prefer dark mode in all my apps\"}],
    \"user_id\": \"curl-test-user\"
    },
    \"http-headers\": {}
    }
    }
    ```

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        body (MemoryoperationsMemoryOperationRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MemoryoperationsMemoryOperationResponse | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503]
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
    body: MemoryoperationsMemoryOperationRequest,
) -> (
    MemoryoperationsMemoryOperationResponse
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503
    | None
):
    r"""Proxy API requests to a remote memory provider

     Forwards REST API requests to a remote memory provider (Mem0, Graphiti, etc.) for agent-specific
    memory operations.
    The memory provider base URL and auth credentials are auto-resolved from management plane config
    based on workspace/MAS/agent IDs.
    The `http-url` field should contain the relative path and query parameters to append to the provider
    base URL.

    **GET example** — retrieve memories:
    ```json
    {
    \"header\": {},
    \"payload\": {
    \"http-request-type\": \"GET\",
    \"http-url\": \"v1/memories/?user_id=curl-test-user\",
    \"http-request-body\": {},
    \"http-headers\": {}
    }
    }
    ```

    **POST example** — add memories:
    ```json
    {
    \"header\": {},
    \"payload\": {
    \"http-request-type\": \"POST\",
    \"http-url\": \"/v1/memories/\",
    \"http-request-body\": {
    \"messages\": [{\"role\": \"user\", \"content\": \"I prefer dark mode in all my apps\"}],
    \"user_id\": \"curl-test-user\"
    },
    \"http-headers\": {}
    }
    }
    ```

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        body (MemoryoperationsMemoryOperationRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MemoryoperationsMemoryOperationResponse | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503
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
    body: MemoryoperationsMemoryOperationRequest,
) -> Response[
    MemoryoperationsMemoryOperationResponse
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503
]:
    r"""Proxy API requests to a remote memory provider

     Forwards REST API requests to a remote memory provider (Mem0, Graphiti, etc.) for agent-specific
    memory operations.
    The memory provider base URL and auth credentials are auto-resolved from management plane config
    based on workspace/MAS/agent IDs.
    The `http-url` field should contain the relative path and query parameters to append to the provider
    base URL.

    **GET example** — retrieve memories:
    ```json
    {
    \"header\": {},
    \"payload\": {
    \"http-request-type\": \"GET\",
    \"http-url\": \"v1/memories/?user_id=curl-test-user\",
    \"http-request-body\": {},
    \"http-headers\": {}
    }
    }
    ```

    **POST example** — add memories:
    ```json
    {
    \"header\": {},
    \"payload\": {
    \"http-request-type\": \"POST\",
    \"http-url\": \"/v1/memories/\",
    \"http-request-body\": {
    \"messages\": [{\"role\": \"user\", \"content\": \"I prefer dark mode in all my apps\"}],
    \"user_id\": \"curl-test-user\"
    },
    \"http-headers\": {}
    }
    }
    ```

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        body (MemoryoperationsMemoryOperationRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MemoryoperationsMemoryOperationResponse | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503]
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
    body: MemoryoperationsMemoryOperationRequest,
) -> (
    MemoryoperationsMemoryOperationResponse
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503
    | None
):
    r"""Proxy API requests to a remote memory provider

     Forwards REST API requests to a remote memory provider (Mem0, Graphiti, etc.) for agent-specific
    memory operations.
    The memory provider base URL and auth credentials are auto-resolved from management plane config
    based on workspace/MAS/agent IDs.
    The `http-url` field should contain the relative path and query parameters to append to the provider
    base URL.

    **GET example** — retrieve memories:
    ```json
    {
    \"header\": {},
    \"payload\": {
    \"http-request-type\": \"GET\",
    \"http-url\": \"v1/memories/?user_id=curl-test-user\",
    \"http-request-body\": {},
    \"http-headers\": {}
    }
    }
    ```

    **POST example** — add memories:
    ```json
    {
    \"header\": {},
    \"payload\": {
    \"http-request-type\": \"POST\",
    \"http-url\": \"/v1/memories/\",
    \"http-request-body\": {
    \"messages\": [{\"role\": \"user\", \"content\": \"I prefer dark mode in all my apps\"}],
    \"user_id\": \"curl-test-user\"
    },
    \"http-headers\": {}
    }
    }
    ```

    Args:
        workspace_id (str):
        mas_id (str):
        agent_id (str):
        body (MemoryoperationsMemoryOperationRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MemoryoperationsMemoryOperationResponse | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse502 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdAgentsAgentIdMemoryOperationsResponse503
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
