from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cognitionengine_heartbeat_response import CognitionengineHeartbeatResponse
from ...models.put_api_cognition_engines_ce_id_heartbeat_response_404 import (
    PutApiCognitionEnginesCeIdHeartbeatResponse404,
)
from ...models.put_api_cognition_engines_ce_id_heartbeat_response_502 import (
    PutApiCognitionEnginesCeIdHeartbeatResponse502,
)
from ...models.put_api_cognition_engines_ce_id_heartbeat_response_503 import (
    PutApiCognitionEnginesCeIdHeartbeatResponse503,
)
from ...types import Response


def _get_kwargs(
    ce_id: str,
) -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/cognition-engines/{ce_id}/heartbeat".format(
            ce_id=quote(str(ce_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    CognitionengineHeartbeatResponse
    | PutApiCognitionEnginesCeIdHeartbeatResponse404
    | PutApiCognitionEnginesCeIdHeartbeatResponse502
    | PutApiCognitionEnginesCeIdHeartbeatResponse503
    | None
):
    if response.status_code == 200:
        response_200 = CognitionengineHeartbeatResponse.from_dict(response.json())

        return response_200

    if response.status_code == 404:
        response_404 = PutApiCognitionEnginesCeIdHeartbeatResponse404.from_dict(response.json())

        return response_404

    if response.status_code == 502:
        response_502 = PutApiCognitionEnginesCeIdHeartbeatResponse502.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = PutApiCognitionEnginesCeIdHeartbeatResponse503.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    CognitionengineHeartbeatResponse
    | PutApiCognitionEnginesCeIdHeartbeatResponse404
    | PutApiCognitionEnginesCeIdHeartbeatResponse502
    | PutApiCognitionEnginesCeIdHeartbeatResponse503
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
) -> Response[
    CognitionengineHeartbeatResponse
    | PutApiCognitionEnginesCeIdHeartbeatResponse404
    | PutApiCognitionEnginesCeIdHeartbeatResponse502
    | PutApiCognitionEnginesCeIdHeartbeatResponse503
]:
    r"""Proxy CE heartbeat to management plane

     Receives heartbeat requests from a Cognition Engine and forwards them to the management plane.
    The management plane updates the CE's last_seen timestamp and status (offline → online if
    applicable).

    CEs should call this endpoint every 30 seconds to maintain their online status.

    **Response example**:
    ```json
    {
    \"status\": \"online\",
    \"last_seen\": \"2026-05-21T10:30:00Z\"
    }
    ```

    Args:
        ce_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineHeartbeatResponse | PutApiCognitionEnginesCeIdHeartbeatResponse404 | PutApiCognitionEnginesCeIdHeartbeatResponse502 | PutApiCognitionEnginesCeIdHeartbeatResponse503]
    """

    kwargs = _get_kwargs(
        ce_id=ce_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> (
    CognitionengineHeartbeatResponse
    | PutApiCognitionEnginesCeIdHeartbeatResponse404
    | PutApiCognitionEnginesCeIdHeartbeatResponse502
    | PutApiCognitionEnginesCeIdHeartbeatResponse503
    | None
):
    r"""Proxy CE heartbeat to management plane

     Receives heartbeat requests from a Cognition Engine and forwards them to the management plane.
    The management plane updates the CE's last_seen timestamp and status (offline → online if
    applicable).

    CEs should call this endpoint every 30 seconds to maintain their online status.

    **Response example**:
    ```json
    {
    \"status\": \"online\",
    \"last_seen\": \"2026-05-21T10:30:00Z\"
    }
    ```

    Args:
        ce_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineHeartbeatResponse | PutApiCognitionEnginesCeIdHeartbeatResponse404 | PutApiCognitionEnginesCeIdHeartbeatResponse502 | PutApiCognitionEnginesCeIdHeartbeatResponse503
    """

    return sync_detailed(
        ce_id=ce_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    CognitionengineHeartbeatResponse
    | PutApiCognitionEnginesCeIdHeartbeatResponse404
    | PutApiCognitionEnginesCeIdHeartbeatResponse502
    | PutApiCognitionEnginesCeIdHeartbeatResponse503
]:
    r"""Proxy CE heartbeat to management plane

     Receives heartbeat requests from a Cognition Engine and forwards them to the management plane.
    The management plane updates the CE's last_seen timestamp and status (offline → online if
    applicable).

    CEs should call this endpoint every 30 seconds to maintain their online status.

    **Response example**:
    ```json
    {
    \"status\": \"online\",
    \"last_seen\": \"2026-05-21T10:30:00Z\"
    }
    ```

    Args:
        ce_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineHeartbeatResponse | PutApiCognitionEnginesCeIdHeartbeatResponse404 | PutApiCognitionEnginesCeIdHeartbeatResponse502 | PutApiCognitionEnginesCeIdHeartbeatResponse503]
    """

    kwargs = _get_kwargs(
        ce_id=ce_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    ce_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> (
    CognitionengineHeartbeatResponse
    | PutApiCognitionEnginesCeIdHeartbeatResponse404
    | PutApiCognitionEnginesCeIdHeartbeatResponse502
    | PutApiCognitionEnginesCeIdHeartbeatResponse503
    | None
):
    r"""Proxy CE heartbeat to management plane

     Receives heartbeat requests from a Cognition Engine and forwards them to the management plane.
    The management plane updates the CE's last_seen timestamp and status (offline → online if
    applicable).

    CEs should call this endpoint every 30 seconds to maintain their online status.

    **Response example**:
    ```json
    {
    \"status\": \"online\",
    \"last_seen\": \"2026-05-21T10:30:00Z\"
    }
    ```

    Args:
        ce_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineHeartbeatResponse | PutApiCognitionEnginesCeIdHeartbeatResponse404 | PutApiCognitionEnginesCeIdHeartbeatResponse502 | PutApiCognitionEnginesCeIdHeartbeatResponse503
    """

    return (
        await asyncio_detailed(
            ce_id=ce_id,
            client=client,
        )
    ).parsed
