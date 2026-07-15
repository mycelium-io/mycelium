from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_alignment_decide_response_400 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_alignment_decide_response_404 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404,
)
from ...models.post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_alignment_decide_response_500 import (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500,
)
from ...models.semanticalignment_decide_request import SemanticalignmentDecideRequest
from ...models.semanticalignment_decide_response import SemanticalignmentDecideResponse
from ...types import Response


def _get_kwargs(
    workspace_id: str,
    mas_id: str,
    *,
    body: SemanticalignmentDecideRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/semantic-alignment/decide".format(
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
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500
    | SemanticalignmentDecideResponse
    | None
):
    if response.status_code == 200:
        response_200 = SemanticalignmentDecideResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400.from_dict(
            response.json()
        )

        return response_400

    if response.status_code == 404:
        response_404 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404.from_dict(
            response.json()
        )

        return response_404

    if response.status_code == 500:
        response_500 = PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500.from_dict(
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
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500
    | SemanticalignmentDecideResponse
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
    body: SemanticalignmentDecideRequest,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500
    | SemanticalignmentDecideResponse
]:
    """Advance semantic alignment session

     Advances an existing semantic alignment session with agent replies.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SemanticalignmentDecideRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500 | SemanticalignmentDecideResponse]
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
    body: SemanticalignmentDecideRequest,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500
    | SemanticalignmentDecideResponse
    | None
):
    """Advance semantic alignment session

     Advances an existing semantic alignment session with agent replies.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SemanticalignmentDecideRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500 | SemanticalignmentDecideResponse
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
    body: SemanticalignmentDecideRequest,
) -> Response[
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500
    | SemanticalignmentDecideResponse
]:
    """Advance semantic alignment session

     Advances an existing semantic alignment session with agent replies.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SemanticalignmentDecideRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500 | SemanticalignmentDecideResponse]
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
    body: SemanticalignmentDecideRequest,
) -> (
    PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404
    | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500
    | SemanticalignmentDecideResponse
    | None
):
    """Advance semantic alignment session

     Advances an existing semantic alignment session with agent replies.

    Args:
        workspace_id (str):
        mas_id (str):
        body (SemanticalignmentDecideRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse400 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse404 | PostApiWorkspacesWorkspaceIdMultiAgenticSystemsMasIdSemanticAlignmentDecideResponse500 | SemanticalignmentDecideResponse
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            client=client,
            body=body,
        )
    ).parsed
