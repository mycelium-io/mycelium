from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.ingest_stats_response import IngestStatsResponse
from ...types import Response


def _get_kwargs() -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/knowledge/ingest/stats",
    }

    return _kwargs


def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> IngestStatsResponse | None:
    if response.status_code == 200:
        response_200 = IngestStatsResponse.from_dict(response.json())

        return response_200

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[IngestStatsResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
) -> Response[IngestStatsResponse]:
    """Knowledge Ingest Stats

     Aggregate CFN ingest activity across the current in-memory buffer.

    Grouped by ``mas_id`` and ``agent_id``. ``last_hour`` is a rolling window
    over the buffer. Buffer resets on backend restart, so these are
    process-lifetime numbers, not durable metrics.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[IngestStatsResponse]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
) -> IngestStatsResponse | None:
    """Knowledge Ingest Stats

     Aggregate CFN ingest activity across the current in-memory buffer.

    Grouped by ``mas_id`` and ``agent_id``. ``last_hour`` is a rolling window
    over the buffer. Buffer resets on backend restart, so these are
    process-lifetime numbers, not durable metrics.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        IngestStatsResponse
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
) -> Response[IngestStatsResponse]:
    """Knowledge Ingest Stats

     Aggregate CFN ingest activity across the current in-memory buffer.

    Grouped by ``mas_id`` and ``agent_id``. ``last_hour`` is a rolling window
    over the buffer. Buffer resets on backend restart, so these are
    process-lifetime numbers, not durable metrics.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[IngestStatsResponse]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
) -> IngestStatsResponse | None:
    """Knowledge Ingest Stats

     Aggregate CFN ingest activity across the current in-memory buffer.

    Grouped by ``mas_id`` and ``agent_id``. ``last_hour`` is a rolling window
    over the buffer. Buffer resets on backend restart, so these are
    process-lifetime numbers, not durable metrics.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        IngestStatsResponse
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
