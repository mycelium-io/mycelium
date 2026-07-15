from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_shared_memories_response_400 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400,
)
from ...models.sharedmemory_create_or_update_accepted_response import (
    SharedmemoryCreateOrUpdateAcceptedResponse,
)
from ...models.sharedmemory_create_or_update_request import SharedmemoryCreateOrUpdateRequest
from ...types import UNSET, Response, Unset


def _get_kwargs(
    workspace_id: str,
    mas_id: str,
    *,
    body: SharedmemoryCreateOrUpdateRequest | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/shared-memories".format(
            workspace_id=quote(str(workspace_id), safe=""),
            mas_id=quote(str(mas_id), safe=""),
        ),
    }

    if not isinstance(body, Unset):
        _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400
    | SharedmemoryCreateOrUpdateAcceptedResponse
    | None
):
    if response.status_code == 202:
        response_202 = SharedmemoryCreateOrUpdateAcceptedResponse.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = (
            PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400.from_dict(
                response.json()
            )
        )

        return response_400

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400
    | SharedmemoryCreateOrUpdateAcceptedResponse
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
    body: SharedmemoryCreateOrUpdateRequest | Unset = UNSET,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400
    | SharedmemoryCreateOrUpdateAcceptedResponse
]:
    """Create or update shared memories (async).

     Accepts a request to create or update shared memories and processes it asynchronously. Returns 202
    Accepted immediately. The extraction and storage operations run in the background.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SharedmemoryCreateOrUpdateRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400 | SharedmemoryCreateOrUpdateAcceptedResponse]
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
    body: SharedmemoryCreateOrUpdateRequest | Unset = UNSET,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400
    | SharedmemoryCreateOrUpdateAcceptedResponse
    | None
):
    """Create or update shared memories (async).

     Accepts a request to create or update shared memories and processes it asynchronously. Returns 202
    Accepted immediately. The extraction and storage operations run in the background.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SharedmemoryCreateOrUpdateRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400 | SharedmemoryCreateOrUpdateAcceptedResponse
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
    body: SharedmemoryCreateOrUpdateRequest | Unset = UNSET,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400
    | SharedmemoryCreateOrUpdateAcceptedResponse
]:
    """Create or update shared memories (async).

     Accepts a request to create or update shared memories and processes it asynchronously. Returns 202
    Accepted immediately. The extraction and storage operations run in the background.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SharedmemoryCreateOrUpdateRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400 | SharedmemoryCreateOrUpdateAcceptedResponse]
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
    body: SharedmemoryCreateOrUpdateRequest | Unset = UNSET,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400
    | SharedmemoryCreateOrUpdateAcceptedResponse
    | None
):
    """Create or update shared memories (async).

     Accepts a request to create or update shared memories and processes it asynchronously. Returns 202
    Accepted immediately. The extraction and storage operations run in the background.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SharedmemoryCreateOrUpdateRequest | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSharedMemoriesResponse400 | SharedmemoryCreateOrUpdateAcceptedResponse
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            client=client,
            body=body,
        )
    ).parsed
