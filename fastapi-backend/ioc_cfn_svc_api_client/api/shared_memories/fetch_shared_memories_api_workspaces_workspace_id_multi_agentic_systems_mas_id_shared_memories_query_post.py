from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.query_request import QueryRequest
from ...models.query_response import QueryResponse
from ...types import Response


def _get_kwargs(
    workspace_id: str,
    mas_id: str,
    *,
    body: QueryRequest,
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
) -> HTTPValidationError | QueryResponse | None:
    if response.status_code == 200:
        response_200 = QueryResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | QueryResponse]:
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
    body: QueryRequest,
) -> Response[HTTPValidationError | QueryResponse]:
    """Fetch Shared Memories

    Args:
        workspace_id (str): Workspace ID
        mas_id (str): Multi-Agentic System ID
        body (QueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | QueryResponse]
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
    body: QueryRequest,
) -> HTTPValidationError | QueryResponse | None:
    """Fetch Shared Memories

    Args:
        workspace_id (str): Workspace ID
        mas_id (str): Multi-Agentic System ID
        body (QueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | QueryResponse
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
    body: QueryRequest,
) -> Response[HTTPValidationError | QueryResponse]:
    """Fetch Shared Memories

    Args:
        workspace_id (str): Workspace ID
        mas_id (str): Multi-Agentic System ID
        body (QueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | QueryResponse]
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
    body: QueryRequest,
) -> HTTPValidationError | QueryResponse | None:
    """Fetch Shared Memories

    Args:
        workspace_id (str): Workspace ID
        mas_id (str): Multi-Agentic System ID
        body (QueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | QueryResponse
    """

    return (
        await asyncio_detailed(
            workspace_id=workspace_id,
            mas_id=mas_id,
            client=client,
            body=body,
        )
    ).parsed
