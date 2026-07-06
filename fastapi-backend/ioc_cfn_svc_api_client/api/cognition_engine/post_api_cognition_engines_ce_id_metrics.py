from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.app_ingest_ce_metrics_request import AppIngestCEMetricsRequest
from ...models.post_api_cognition_engines_ce_id_metrics_response_202 import (
    PostApiCognitionEnginesCeIdMetricsResponse202,
)
from ...models.post_api_cognition_engines_ce_id_metrics_response_400 import (
    PostApiCognitionEnginesCeIdMetricsResponse400,
)
from ...types import Response


def _get_kwargs(
    ce_id: str,
    *,
    body: AppIngestCEMetricsRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/cognition-engines/{ce_id}/metrics".format(
            ce_id=quote(str(ce_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    PostApiCognitionEnginesCeIdMetricsResponse202
    | PostApiCognitionEnginesCeIdMetricsResponse400
    | None
):
    if response.status_code == 202:
        response_202 = PostApiCognitionEnginesCeIdMetricsResponse202.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = PostApiCognitionEnginesCeIdMetricsResponse400.from_dict(response.json())

        return response_400

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    PostApiCognitionEnginesCeIdMetricsResponse202 | PostApiCognitionEnginesCeIdMetricsResponse400
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: AppIngestCEMetricsRequest,
) -> Response[
    PostApiCognitionEnginesCeIdMetricsResponse202 | PostApiCognitionEnginesCeIdMetricsResponse400
]:
    """Ingest CE infrastructure metrics

     Accepts batch of CE infrastructure metrics (queue depth, memory, CPU, active requests) and stores in
    TimescaleDB asynchronously.

    Args:
        ce_id (str):
        body (AppIngestCEMetricsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiCognitionEnginesCeIdMetricsResponse202 | PostApiCognitionEnginesCeIdMetricsResponse400]
    """

    kwargs = _get_kwargs(
        ce_id=ce_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: AppIngestCEMetricsRequest,
) -> (
    PostApiCognitionEnginesCeIdMetricsResponse202
    | PostApiCognitionEnginesCeIdMetricsResponse400
    | None
):
    """Ingest CE infrastructure metrics

     Accepts batch of CE infrastructure metrics (queue depth, memory, CPU, active requests) and stores in
    TimescaleDB asynchronously.

    Args:
        ce_id (str):
        body (AppIngestCEMetricsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiCognitionEnginesCeIdMetricsResponse202 | PostApiCognitionEnginesCeIdMetricsResponse400
    """

    return sync_detailed(
        ce_id=ce_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: AppIngestCEMetricsRequest,
) -> Response[
    PostApiCognitionEnginesCeIdMetricsResponse202 | PostApiCognitionEnginesCeIdMetricsResponse400
]:
    """Ingest CE infrastructure metrics

     Accepts batch of CE infrastructure metrics (queue depth, memory, CPU, active requests) and stores in
    TimescaleDB asynchronously.

    Args:
        ce_id (str):
        body (AppIngestCEMetricsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PostApiCognitionEnginesCeIdMetricsResponse202 | PostApiCognitionEnginesCeIdMetricsResponse400]
    """

    kwargs = _get_kwargs(
        ce_id=ce_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: AppIngestCEMetricsRequest,
) -> (
    PostApiCognitionEnginesCeIdMetricsResponse202
    | PostApiCognitionEnginesCeIdMetricsResponse400
    | None
):
    """Ingest CE infrastructure metrics

     Accepts batch of CE infrastructure metrics (queue depth, memory, CPU, active requests) and stores in
    TimescaleDB asynchronously.

    Args:
        ce_id (str):
        body (AppIngestCEMetricsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PostApiCognitionEnginesCeIdMetricsResponse202 | PostApiCognitionEnginesCeIdMetricsResponse400
    """

    return (
        await asyncio_detailed(
            ce_id=ce_id,
            client=client,
            body=body,
        )
    ).parsed
