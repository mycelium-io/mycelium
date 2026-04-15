from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.knowledge_ingest_request import KnowledgeIngestRequest
from ...models.knowledge_ingest_response import KnowledgeIngestResponse
from ...types import Response


def _get_kwargs(
    *,
    body: KnowledgeIngestRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/knowledge/ingest",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | KnowledgeIngestResponse | None:
    if response.status_code == 200:
        response_200 = KnowledgeIngestResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | KnowledgeIngestResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: KnowledgeIngestRequest,
) -> Response[HTTPValidationError | KnowledgeIngestResponse]:
    """Knowledge Ingest

     Forward openclaw turns to CFN's shared-memories endpoint.

    Enforces user-configured gates before hitting CFN:

    1. ``MYCELIUM_INGEST_ENABLED`` master switch — accept+discard when false.
    2. ``MYCELIUM_INGEST_MAX_INPUT_TOKENS`` circuit breaker — refuse with
       HTTP 413 when the estimated input exceeds the threshold.
    3. Content-hash dedupe cache — short-circuit duplicate payloads within
       ``MYCELIUM_INGEST_DEDUPE_TTL_SECONDS`` and return the cached
       ``response_id`` without re-hitting CFN.

    Every outcome is appended to the in-memory ingest log buffer so
    ``mycelium cfn log`` / ``stats`` can surface cost and success signal.
    The durable ``KNOWLEDGE_INGESTION`` audit event is still emitted for
    every accepted attempt (ok, deduped, disabled) — it stays as the
    tamper-evident record and is unaffected by the in-memory buffer.

    Args:
        body (KnowledgeIngestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | KnowledgeIngestResponse]
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
    body: KnowledgeIngestRequest,
) -> HTTPValidationError | KnowledgeIngestResponse | None:
    """Knowledge Ingest

     Forward openclaw turns to CFN's shared-memories endpoint.

    Enforces user-configured gates before hitting CFN:

    1. ``MYCELIUM_INGEST_ENABLED`` master switch — accept+discard when false.
    2. ``MYCELIUM_INGEST_MAX_INPUT_TOKENS`` circuit breaker — refuse with
       HTTP 413 when the estimated input exceeds the threshold.
    3. Content-hash dedupe cache — short-circuit duplicate payloads within
       ``MYCELIUM_INGEST_DEDUPE_TTL_SECONDS`` and return the cached
       ``response_id`` without re-hitting CFN.

    Every outcome is appended to the in-memory ingest log buffer so
    ``mycelium cfn log`` / ``stats`` can surface cost and success signal.
    The durable ``KNOWLEDGE_INGESTION`` audit event is still emitted for
    every accepted attempt (ok, deduped, disabled) — it stays as the
    tamper-evident record and is unaffected by the in-memory buffer.

    Args:
        body (KnowledgeIngestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | KnowledgeIngestResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: KnowledgeIngestRequest,
) -> Response[HTTPValidationError | KnowledgeIngestResponse]:
    """Knowledge Ingest

     Forward openclaw turns to CFN's shared-memories endpoint.

    Enforces user-configured gates before hitting CFN:

    1. ``MYCELIUM_INGEST_ENABLED`` master switch — accept+discard when false.
    2. ``MYCELIUM_INGEST_MAX_INPUT_TOKENS`` circuit breaker — refuse with
       HTTP 413 when the estimated input exceeds the threshold.
    3. Content-hash dedupe cache — short-circuit duplicate payloads within
       ``MYCELIUM_INGEST_DEDUPE_TTL_SECONDS`` and return the cached
       ``response_id`` without re-hitting CFN.

    Every outcome is appended to the in-memory ingest log buffer so
    ``mycelium cfn log`` / ``stats`` can surface cost and success signal.
    The durable ``KNOWLEDGE_INGESTION`` audit event is still emitted for
    every accepted attempt (ok, deduped, disabled) — it stays as the
    tamper-evident record and is unaffected by the in-memory buffer.

    Args:
        body (KnowledgeIngestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | KnowledgeIngestResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: KnowledgeIngestRequest,
) -> HTTPValidationError | KnowledgeIngestResponse | None:
    """Knowledge Ingest

     Forward openclaw turns to CFN's shared-memories endpoint.

    Enforces user-configured gates before hitting CFN:

    1. ``MYCELIUM_INGEST_ENABLED`` master switch — accept+discard when false.
    2. ``MYCELIUM_INGEST_MAX_INPUT_TOKENS`` circuit breaker — refuse with
       HTTP 413 when the estimated input exceeds the threshold.
    3. Content-hash dedupe cache — short-circuit duplicate payloads within
       ``MYCELIUM_INGEST_DEDUPE_TTL_SECONDS`` and return the cached
       ``response_id`` without re-hitting CFN.

    Every outcome is appended to the in-memory ingest log buffer so
    ``mycelium cfn log`` / ``stats`` can surface cost and success signal.
    The durable ``KNOWLEDGE_INGESTION`` audit event is still emitted for
    every accepted attempt (ok, deduped, disabled) — it stays as the
    tamper-evident record and is unaffected by the in-memory buffer.

    Args:
        body (KnowledgeIngestRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | KnowledgeIngestResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
