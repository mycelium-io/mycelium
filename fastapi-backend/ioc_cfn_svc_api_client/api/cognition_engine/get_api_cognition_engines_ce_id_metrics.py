from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.app_metrics_query_response import AppMetricsQueryResponse
from ...models.get_api_cognition_engines_ce_id_metrics_response_400 import (
    GetApiCognitionEnginesCeIdMetricsResponse400,
)
from ...models.get_api_cognition_engines_ce_id_metrics_response_413 import (
    GetApiCognitionEnginesCeIdMetricsResponse413,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    ce_id: str,
    *,
    start_time: str,
    end_time: str,
    workspace_id: str | Unset = UNSET,
    mas_id: str | Unset = UNSET,
    agent_id: str | Unset = UNSET,
    metric_name: str | Unset = UNSET,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["start_time"] = start_time

    params["end_time"] = end_time

    params["workspace_id"] = workspace_id

    params["mas_id"] = mas_id

    params["agent_id"] = agent_id

    params["metric_name"] = metric_name

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/cognition-engines/{ce_id}/metrics".format(
            ce_id=quote(str(ce_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    AppMetricsQueryResponse
    | GetApiCognitionEnginesCeIdMetricsResponse400
    | GetApiCognitionEnginesCeIdMetricsResponse413
    | None
):
    if response.status_code == 200:
        response_200 = AppMetricsQueryResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = GetApiCognitionEnginesCeIdMetricsResponse400.from_dict(response.json())

        return response_400

    if response.status_code == 413:
        response_413 = GetApiCognitionEnginesCeIdMetricsResponse413.from_dict(response.json())

        return response_413

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    AppMetricsQueryResponse
    | GetApiCognitionEnginesCeIdMetricsResponse400
    | GetApiCognitionEnginesCeIdMetricsResponse413
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
    start_time: str,
    end_time: str,
    workspace_id: str | Unset = UNSET,
    mas_id: str | Unset = UNSET,
    agent_id: str | Unset = UNSET,
    metric_name: str | Unset = UNSET,
) -> Response[
    AppMetricsQueryResponse
    | GetApiCognitionEnginesCeIdMetricsResponse400
    | GetApiCognitionEnginesCeIdMetricsResponse413
]:
    """Query metrics within time range (CE and/or MAS)

     Returns grouped time-series data filtered by time and entity dimensions.
    Returns both CE infrastructure metrics (queue, memory, CPU) and MAS operation metrics (tokens,
    latency, cost) processed by this CE.
    Response format groups datapoints by metric name to reduce verbosity (60-70% size reduction).
    No pagination - queries return all matching datapoints up to safety limit (100K max).

    Args:
        ce_id (str):
        start_time (str):
        end_time (str):
        workspace_id (str | Unset):
        mas_id (str | Unset):
        agent_id (str | Unset):
        metric_name (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AppMetricsQueryResponse | GetApiCognitionEnginesCeIdMetricsResponse400 | GetApiCognitionEnginesCeIdMetricsResponse413]
    """

    kwargs = _get_kwargs(
        ce_id=ce_id,
        start_time=start_time,
        end_time=end_time,
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        metric_name=metric_name,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
    start_time: str,
    end_time: str,
    workspace_id: str | Unset = UNSET,
    mas_id: str | Unset = UNSET,
    agent_id: str | Unset = UNSET,
    metric_name: str | Unset = UNSET,
) -> (
    AppMetricsQueryResponse
    | GetApiCognitionEnginesCeIdMetricsResponse400
    | GetApiCognitionEnginesCeIdMetricsResponse413
    | None
):
    """Query metrics within time range (CE and/or MAS)

     Returns grouped time-series data filtered by time and entity dimensions.
    Returns both CE infrastructure metrics (queue, memory, CPU) and MAS operation metrics (tokens,
    latency, cost) processed by this CE.
    Response format groups datapoints by metric name to reduce verbosity (60-70% size reduction).
    No pagination - queries return all matching datapoints up to safety limit (100K max).

    Args:
        ce_id (str):
        start_time (str):
        end_time (str):
        workspace_id (str | Unset):
        mas_id (str | Unset):
        agent_id (str | Unset):
        metric_name (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AppMetricsQueryResponse | GetApiCognitionEnginesCeIdMetricsResponse400 | GetApiCognitionEnginesCeIdMetricsResponse413
    """

    return sync_detailed(
        ce_id=ce_id,
        client=client,
        start_time=start_time,
        end_time=end_time,
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        metric_name=metric_name,
    ).parsed


async def asyncio_detailed(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
    start_time: str,
    end_time: str,
    workspace_id: str | Unset = UNSET,
    mas_id: str | Unset = UNSET,
    agent_id: str | Unset = UNSET,
    metric_name: str | Unset = UNSET,
) -> Response[
    AppMetricsQueryResponse
    | GetApiCognitionEnginesCeIdMetricsResponse400
    | GetApiCognitionEnginesCeIdMetricsResponse413
]:
    """Query metrics within time range (CE and/or MAS)

     Returns grouped time-series data filtered by time and entity dimensions.
    Returns both CE infrastructure metrics (queue, memory, CPU) and MAS operation metrics (tokens,
    latency, cost) processed by this CE.
    Response format groups datapoints by metric name to reduce verbosity (60-70% size reduction).
    No pagination - queries return all matching datapoints up to safety limit (100K max).

    Args:
        ce_id (str):
        start_time (str):
        end_time (str):
        workspace_id (str | Unset):
        mas_id (str | Unset):
        agent_id (str | Unset):
        metric_name (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AppMetricsQueryResponse | GetApiCognitionEnginesCeIdMetricsResponse400 | GetApiCognitionEnginesCeIdMetricsResponse413]
    """

    kwargs = _get_kwargs(
        ce_id=ce_id,
        start_time=start_time,
        end_time=end_time,
        workspace_id=workspace_id,
        mas_id=mas_id,
        agent_id=agent_id,
        metric_name=metric_name,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
    start_time: str,
    end_time: str,
    workspace_id: str | Unset = UNSET,
    mas_id: str | Unset = UNSET,
    agent_id: str | Unset = UNSET,
    metric_name: str | Unset = UNSET,
) -> (
    AppMetricsQueryResponse
    | GetApiCognitionEnginesCeIdMetricsResponse400
    | GetApiCognitionEnginesCeIdMetricsResponse413
    | None
):
    """Query metrics within time range (CE and/or MAS)

     Returns grouped time-series data filtered by time and entity dimensions.
    Returns both CE infrastructure metrics (queue, memory, CPU) and MAS operation metrics (tokens,
    latency, cost) processed by this CE.
    Response format groups datapoints by metric name to reduce verbosity (60-70% size reduction).
    No pagination - queries return all matching datapoints up to safety limit (100K max).

    Args:
        ce_id (str):
        start_time (str):
        end_time (str):
        workspace_id (str | Unset):
        mas_id (str | Unset):
        agent_id (str | Unset):
        metric_name (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AppMetricsQueryResponse | GetApiCognitionEnginesCeIdMetricsResponse400 | GetApiCognitionEnginesCeIdMetricsResponse413
    """

    return (
        await asyncio_detailed(
            ce_id=ce_id,
            client=client,
            start_time=start_time,
            end_time=end_time,
            workspace_id=workspace_id,
            mas_id=mas_id,
            agent_id=agent_id,
            metric_name=metric_name,
        )
    ).parsed
