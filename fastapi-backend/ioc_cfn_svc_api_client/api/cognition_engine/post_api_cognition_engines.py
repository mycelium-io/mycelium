from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cognitionengine_register_request import CognitionengineRegisterRequest
from ...models.cognitionengine_register_response import CognitionengineRegisterResponse
from ...models.post_api_cognition_engines_response_400 import PostApiCognitionEnginesResponse400
from ...models.post_api_cognition_engines_response_502 import PostApiCognitionEnginesResponse502
from ...models.post_api_cognition_engines_response_503 import PostApiCognitionEnginesResponse503
from ...types import Response


def _get_kwargs(
    *,
    body: CognitionengineRegisterRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/cognition-engines",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    CognitionengineRegisterResponse
    | PostApiCognitionEnginesResponse400
    | PostApiCognitionEnginesResponse502
    | PostApiCognitionEnginesResponse503
    | None
):
    if response.status_code == 200:
        response_200 = CognitionengineRegisterResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = PostApiCognitionEnginesResponse400.from_dict(response.json())

        return response_400

    if response.status_code == 502:
        response_502 = PostApiCognitionEnginesResponse502.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = PostApiCognitionEnginesResponse503.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    CognitionengineRegisterResponse
    | PostApiCognitionEnginesResponse400
    | PostApiCognitionEnginesResponse502
    | PostApiCognitionEnginesResponse503
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: CognitionengineRegisterRequest,
) -> Response[
    CognitionengineRegisterResponse
    | PostApiCognitionEnginesResponse400
    | PostApiCognitionEnginesResponse502
    | PostApiCognitionEnginesResponse503
]:
    r"""Register a Cognition Engine with the management plane

     Receives a registration request from a Cognition Engine, adds CFN context (cfn_id),
    and forwards it to the management plane's /api/cognition-engines endpoint.

    **Request example**:
    ```json
    {
    \"name\": \"Knowledge Management CE\",
    \"type\": \"knowledge_management\",
    \"url\": \"http://ce-host:9004\",
    \"capabilities\": [\"ingestion\", \"retrieval\"],
    \"metrics\": [\"kb.documents.indexed\", \"kb.search.latency_ms\"]
    }
    ```

    The CFN service validates the request, injects the CFN ID association,
    and forwards the enriched payload to the management plane.

    Args:
        body (CognitionengineRegisterRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineRegisterResponse | PostApiCognitionEnginesResponse400 | PostApiCognitionEnginesResponse502 | PostApiCognitionEnginesResponse503]
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
    body: CognitionengineRegisterRequest,
) -> (
    CognitionengineRegisterResponse
    | PostApiCognitionEnginesResponse400
    | PostApiCognitionEnginesResponse502
    | PostApiCognitionEnginesResponse503
    | None
):
    r"""Register a Cognition Engine with the management plane

     Receives a registration request from a Cognition Engine, adds CFN context (cfn_id),
    and forwards it to the management plane's /api/cognition-engines endpoint.

    **Request example**:
    ```json
    {
    \"name\": \"Knowledge Management CE\",
    \"type\": \"knowledge_management\",
    \"url\": \"http://ce-host:9004\",
    \"capabilities\": [\"ingestion\", \"retrieval\"],
    \"metrics\": [\"kb.documents.indexed\", \"kb.search.latency_ms\"]
    }
    ```

    The CFN service validates the request, injects the CFN ID association,
    and forwards the enriched payload to the management plane.

    Args:
        body (CognitionengineRegisterRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineRegisterResponse | PostApiCognitionEnginesResponse400 | PostApiCognitionEnginesResponse502 | PostApiCognitionEnginesResponse503
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: CognitionengineRegisterRequest,
) -> Response[
    CognitionengineRegisterResponse
    | PostApiCognitionEnginesResponse400
    | PostApiCognitionEnginesResponse502
    | PostApiCognitionEnginesResponse503
]:
    r"""Register a Cognition Engine with the management plane

     Receives a registration request from a Cognition Engine, adds CFN context (cfn_id),
    and forwards it to the management plane's /api/cognition-engines endpoint.

    **Request example**:
    ```json
    {
    \"name\": \"Knowledge Management CE\",
    \"type\": \"knowledge_management\",
    \"url\": \"http://ce-host:9004\",
    \"capabilities\": [\"ingestion\", \"retrieval\"],
    \"metrics\": [\"kb.documents.indexed\", \"kb.search.latency_ms\"]
    }
    ```

    The CFN service validates the request, injects the CFN ID association,
    and forwards the enriched payload to the management plane.

    Args:
        body (CognitionengineRegisterRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineRegisterResponse | PostApiCognitionEnginesResponse400 | PostApiCognitionEnginesResponse502 | PostApiCognitionEnginesResponse503]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: CognitionengineRegisterRequest,
) -> (
    CognitionengineRegisterResponse
    | PostApiCognitionEnginesResponse400
    | PostApiCognitionEnginesResponse502
    | PostApiCognitionEnginesResponse503
    | None
):
    r"""Register a Cognition Engine with the management plane

     Receives a registration request from a Cognition Engine, adds CFN context (cfn_id),
    and forwards it to the management plane's /api/cognition-engines endpoint.

    **Request example**:
    ```json
    {
    \"name\": \"Knowledge Management CE\",
    \"type\": \"knowledge_management\",
    \"url\": \"http://ce-host:9004\",
    \"capabilities\": [\"ingestion\", \"retrieval\"],
    \"metrics\": [\"kb.documents.indexed\", \"kb.search.latency_ms\"]
    }
    ```

    The CFN service validates the request, injects the CFN ID association,
    and forwards the enriched payload to the management plane.

    Args:
        body (CognitionengineRegisterRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineRegisterResponse | PostApiCognitionEnginesResponse400 | PostApiCognitionEnginesResponse502 | PostApiCognitionEnginesResponse503
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
