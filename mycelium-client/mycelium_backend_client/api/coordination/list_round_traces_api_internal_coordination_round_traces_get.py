from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_round_traces_api_internal_coordination_round_traces_get_response_list_round_traces_api_internal_coordination_round_traces_get import (
    ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    limit: int | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_limit: int | None | Unset
    if isinstance(limit, Unset):
        json_limit = UNSET
    else:
        json_limit = limit
    params["limit"] = json_limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/internal/coordination/round-traces",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet
    | None
):
    if response.status_code == 200:
        response_200 = ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet.from_dict(
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
) -> Response[
    HTTPValidationError
    | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet
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
    limit: int | None | Unset = UNSET,
) -> Response[
    HTTPValidationError
    | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet
]:
    """List Round Traces

     Return completed CFN round traces, oldest first.

    Each trace is one round of a CFN negotiation: who replied, when, whether
    any replies were synthesised because the watchdog fired, and how the
    round closed.  ``round_n`` is per-negotiation (resets to 0 when a new
    negotiation starts in the same room), not per-room-lifetime.  Intended
    for diagnosing coordination latency and synthesis behaviour.

    Args:
        limit (int | None | Unset): Return at most the most-recent N traces.  Omit to return all
            traces currently in the buffer.  Values larger than the buffer capacity simply return the
            whole buffer.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet]
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
    limit: int | None | Unset = UNSET,
) -> (
    HTTPValidationError
    | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet
    | None
):
    """List Round Traces

     Return completed CFN round traces, oldest first.

    Each trace is one round of a CFN negotiation: who replied, when, whether
    any replies were synthesised because the watchdog fired, and how the
    round closed.  ``round_n`` is per-negotiation (resets to 0 when a new
    negotiation starts in the same room), not per-room-lifetime.  Intended
    for diagnosing coordination latency and synthesis behaviour.

    Args:
        limit (int | None | Unset): Return at most the most-recent N traces.  Omit to return all
            traces currently in the buffer.  Values larger than the buffer capacity simply return the
            whole buffer.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet
    """

    return sync_detailed(
        client=client,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    limit: int | None | Unset = UNSET,
) -> Response[
    HTTPValidationError
    | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet
]:
    """List Round Traces

     Return completed CFN round traces, oldest first.

    Each trace is one round of a CFN negotiation: who replied, when, whether
    any replies were synthesised because the watchdog fired, and how the
    round closed.  ``round_n`` is per-negotiation (resets to 0 when a new
    negotiation starts in the same room), not per-room-lifetime.  Intended
    for diagnosing coordination latency and synthesis behaviour.

    Args:
        limit (int | None | Unset): Return at most the most-recent N traces.  Omit to return all
            traces currently in the buffer.  Values larger than the buffer capacity simply return the
            whole buffer.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet]
    """

    kwargs = _get_kwargs(
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    limit: int | None | Unset = UNSET,
) -> (
    HTTPValidationError
    | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet
    | None
):
    """List Round Traces

     Return completed CFN round traces, oldest first.

    Each trace is one round of a CFN negotiation: who replied, when, whether
    any replies were synthesised because the watchdog fired, and how the
    round closed.  ``round_n`` is per-negotiation (resets to 0 when a new
    negotiation starts in the same room), not per-room-lifetime.  Intended
    for diagnosing coordination latency and synthesis behaviour.

    Args:
        limit (int | None | Unset): Return at most the most-recent N traces.  Omit to return all
            traces currently in the buffer.  Values larger than the buffer capacity simply return the
            whole buffer.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ListRoundTracesApiInternalCoordinationRoundTracesGetResponseListRoundTracesApiInternalCoordinationRoundTracesGet
    """

    return (
        await asyncio_detailed(
            client=client,
            limit=limit,
        )
    ).parsed
