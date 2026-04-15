from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cfn_query_api_cfn_knowledge_query_post_response_cfn_query_api_cfn_knowledge_query_post import (
    CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost,
)
from ...models.http_validation_error import HTTPValidationError
from ...models.query_request import QueryRequest
from ...types import Response


def _get_kwargs(
    *,
    body: QueryRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/cfn/knowledge/query",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost.from_dict(
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
) -> Response[CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: QueryRequest,
) -> Response[CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError]:
    r"""Cfn Query

     Semantic-graph query against CFN's shared memory.

    CFN returns a natural-language answer from its evidence agent
    (``{\"response_id\": str, \"message\": str}``), not a structured record
    list. The ``mycelium cfn query`` CLI renders the message directly.

    Args:
        body (QueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError]
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
    body: QueryRequest,
) -> CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError | None:
    r"""Cfn Query

     Semantic-graph query against CFN's shared memory.

    CFN returns a natural-language answer from its evidence agent
    (``{\"response_id\": str, \"message\": str}``), not a structured record
    list. The ``mycelium cfn query`` CLI renders the message directly.

    Args:
        body (QueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: QueryRequest,
) -> Response[CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError]:
    r"""Cfn Query

     Semantic-graph query against CFN's shared memory.

    CFN returns a natural-language answer from its evidence agent
    (``{\"response_id\": str, \"message\": str}``), not a structured record
    list. The ``mycelium cfn query`` CLI renders the message directly.

    Args:
        body (QueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: QueryRequest,
) -> CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError | None:
    r"""Cfn Query

     Semantic-graph query against CFN's shared memory.

    CFN returns a natural-language answer from its evidence agent
    (``{\"response_id\": str, \"message\": str}``), not a structured record
    list. The ``mycelium cfn query`` CLI renders the message directly.

    Args:
        body (QueryRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CfnQueryApiCfnKnowledgeQueryPostResponseCfnQueryApiCfnKnowledgeQueryPost | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
