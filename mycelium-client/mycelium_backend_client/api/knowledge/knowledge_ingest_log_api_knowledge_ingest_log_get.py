from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.ingest_log_response import IngestLogResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    limit: int | Unset = 50,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/knowledge/ingest/log",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | IngestLogResponse | None:
    if response.status_code == 200:
        response_200 = IngestLogResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | IngestLogResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 50,
) -> Response[HTTPValidationError | IngestLogResponse]:
    """Knowledge Ingest Log

     Return the most recent CFN shared-memories forward attempts.

    Newest first. Resets on backend restart. Captures both successes and
    failures; ``error`` is set on failures, ``cfn_message`` on successes.

    Args:
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | IngestLogResponse]
    """

    kwargs = _get_kwargs(
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 50,
) -> HTTPValidationError | IngestLogResponse | None:
    """Knowledge Ingest Log

     Return the most recent CFN shared-memories forward attempts.

    Newest first. Resets on backend restart. Captures both successes and
    failures; ``error`` is set on failures, ``cfn_message`` on successes.

    Args:
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | IngestLogResponse
    """

    return sync_detailed(
        client=client,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 50,
) -> Response[HTTPValidationError | IngestLogResponse]:
    """Knowledge Ingest Log

     Return the most recent CFN shared-memories forward attempts.

    Newest first. Resets on backend restart. Captures both successes and
    failures; ``error`` is set on failures, ``cfn_message`` on successes.

    Args:
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | IngestLogResponse]
    """

    kwargs = _get_kwargs(
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 50,
) -> HTTPValidationError | IngestLogResponse | None:
    """Knowledge Ingest Log

     Return the most recent CFN shared-memories forward attempts.

    Newest first. Resets on backend restart. Captures both successes and
    failures; ``error`` is set on failures, ``cfn_message`` on successes.

    Args:
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | IngestLogResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            limit=limit,
        )
    ).parsed
