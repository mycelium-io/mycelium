from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_alignment_start_response_400 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_alignment_start_response_500 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500,
)
from ...models.semanticalignment_start_request import SemanticalignmentStartRequest
from ...models.semanticalignment_start_response import SemanticalignmentStartResponse
from ...types import Response


def _get_kwargs(
    workspace_id: str,
    mas_id: str,
    *,
    body: SemanticalignmentStartRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/semantic-alignment/start".format(
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
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500
    | SemanticalignmentStartResponse
    | None
):
    if response.status_code == 200:
        response_200 = SemanticalignmentStartResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400.from_dict(
            response.json()
        )

        return response_400

    if response.status_code == 500:
        response_500 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500.from_dict(
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
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500
    | SemanticalignmentStartResponse
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
    body: SemanticalignmentStartRequest,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500
    | SemanticalignmentStartResponse
]:
    """Start semantic alignment session

     Initiates a new semantic alignment session with multiple agents.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SemanticalignmentStartRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500 | SemanticalignmentStartResponse]
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
    body: SemanticalignmentStartRequest,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500
    | SemanticalignmentStartResponse
    | None
):
    """Start semantic alignment session

     Initiates a new semantic alignment session with multiple agents.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SemanticalignmentStartRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500 | SemanticalignmentStartResponse
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
    body: SemanticalignmentStartRequest,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500
    | SemanticalignmentStartResponse
]:
    """Start semantic alignment session

     Initiates a new semantic alignment session with multiple agents.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SemanticalignmentStartRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500 | SemanticalignmentStartResponse]
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
    body: SemanticalignmentStartRequest,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500
    | SemanticalignmentStartResponse
    | None
):
    """Start semantic alignment session

     Initiates a new semantic alignment session with multiple agents.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SemanticalignmentStartRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentStartResponse500 | SemanticalignmentStartResponse
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            client=client,
            body=body,
        )
    ).parsed
