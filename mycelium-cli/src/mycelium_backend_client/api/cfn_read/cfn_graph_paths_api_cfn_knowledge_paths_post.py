from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cfn_graph_paths_api_cfn_knowledge_paths_post_response_cfn_graph_paths_api_cfn_knowledge_paths_post import (
    CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost,
)
from ...models.graph_paths_request import GraphPathsRequest
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    *,
    body: GraphPathsRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/cfn/knowledge/paths",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost.from_dict(
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
) -> Response[CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: GraphPathsRequest,
) -> Response[CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError]:
    """Cfn Graph Paths

     Fetch paths between two CFN concepts by ID.

    Args:
        body (GraphPathsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: GraphPathsRequest,
) -> CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError | None:
    """Cfn Graph Paths

     Fetch paths between two CFN concepts by ID.

    Args:
        body (GraphPathsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: GraphPathsRequest,
) -> Response[CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError]:
    """Cfn Graph Paths

     Fetch paths between two CFN concepts by ID.

    Args:
        body (GraphPathsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: GraphPathsRequest,
) -> CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError | None:
    """Cfn Graph Paths

     Fetch paths between two CFN concepts by ID.

    Args:
        body (GraphPathsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CfnGraphPathsApiCfnKnowledgePathsPostResponseCfnGraphPathsApiCfnKnowledgePathsPost | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
