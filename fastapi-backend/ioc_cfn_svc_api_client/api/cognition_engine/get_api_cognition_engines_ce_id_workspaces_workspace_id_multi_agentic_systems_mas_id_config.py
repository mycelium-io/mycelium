from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cognitionengine_masce_config_response import CognitionengineMASCEConfigResponse
from ...models.get_api_cognition_engines_ce_id_workspaces_workspace_id_multi_agentic_systems_mas_id_config_response_400 import (
    GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400,
)
from ...models.get_api_cognition_engines_ce_id_workspaces_workspace_id_multi_agentic_systems_mas_id_config_response_404 import (
    GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404,
)
from ...models.get_api_cognition_engines_ce_id_workspaces_workspace_id_multi_agentic_systems_mas_id_config_response_502 import (
    GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502,
)
from ...models.get_api_cognition_engines_ce_id_workspaces_workspace_id_multi_agentic_systems_mas_id_config_response_503 import (
    GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503,
)
from ...types import Response


def _get_kwargs(
    ce_id: str,
    workspace_id: str,
    mas_id: str,
) -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/cognition-engines/{ce_id}/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/config".format(
            ce_id=quote(str(ce_id), safe=""),
            workspace_id=quote(str(workspace_id), safe=""),
            mas_id=quote(str(mas_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    CognitionengineMASCEConfigResponse
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503
    | None
):
    if response.status_code == 200:
        response_200 = CognitionengineMASCEConfigResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400.from_dict(
            response.json()
        )

        return response_400

    if response.status_code == 404:
        response_404 = GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404.from_dict(
            response.json()
        )

        return response_404

    if response.status_code == 502:
        response_502 = GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502.from_dict(
            response.json()
        )

        return response_502

    if response.status_code == 503:
        response_503 = GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503.from_dict(
            response.json()
        )

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    CognitionengineMASCEConfigResponse
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    ce_id: str,
    workspace_id: str,
    mas_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    CognitionengineMASCEConfigResponse
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503
]:
    """Get per-MAS config for a Cognition Engine

     Returns the per-MAS mas_config override for this CE associated with a specific MAS.
    This is the resolved config from mas_cognition_engines.mas_config, not the CE-wide
    factory defaults from cognition_engines.mas_config.

    The endpoint is CE-centric: a CE presents its identifier and requests its config
    for a specific workspace/MAS combination.

    Args:
        ce_id (str):
        workspace_id (str):
        mas_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineMASCEConfigResponse | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503]
    """

    kwargs = _get_kwargs(
        ce_id=ce_id,
        workspace_id=workspace_id,
        mas_id=mas_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    ce_id: str,
    workspace_id: str,
    mas_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> (
    CognitionengineMASCEConfigResponse
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503
    | None
):
    """Get per-MAS config for a Cognition Engine

     Returns the per-MAS mas_config override for this CE associated with a specific MAS.
    This is the resolved config from mas_cognition_engines.mas_config, not the CE-wide
    factory defaults from cognition_engines.mas_config.

    The endpoint is CE-centric: a CE presents its identifier and requests its config
    for a specific workspace/MAS combination.

    Args:
        ce_id (str):
        workspace_id (str):
        mas_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineMASCEConfigResponse | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503
    """

    return sync_detailed(
        ce_id=ce_id,
        workspace_id=workspace_id,
        mas_id=mas_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    ce_id: str,
    workspace_id: str,
    mas_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    CognitionengineMASCEConfigResponse
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503
]:
    """Get per-MAS config for a Cognition Engine

     Returns the per-MAS mas_config override for this CE associated with a specific MAS.
    This is the resolved config from mas_cognition_engines.mas_config, not the CE-wide
    factory defaults from cognition_engines.mas_config.

    The endpoint is CE-centric: a CE presents its identifier and requests its config
    for a specific workspace/MAS combination.

    Args:
        ce_id (str):
        workspace_id (str):
        mas_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineMASCEConfigResponse | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503]
    """

    kwargs = _get_kwargs(
        ce_id=ce_id,
        workspace_id=workspace_id,
        mas_id=mas_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    ce_id: str,
    workspace_id: str,
    mas_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> (
    CognitionengineMASCEConfigResponse
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502
    | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503
    | None
):
    """Get per-MAS config for a Cognition Engine

     Returns the per-MAS mas_config override for this CE associated with a specific MAS.
    This is the resolved config from mas_cognition_engines.mas_config, not the CE-wide
    factory defaults from cognition_engines.mas_config.

    The endpoint is CE-centric: a CE presents its identifier and requests its config
    for a specific workspace/MAS combination.

    Args:
        ce_id (str):
        workspace_id (str):
        mas_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineMASCEConfigResponse | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse400 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse404 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse502 | GetApiCognitionEnginesCeIdWorkspacesWorkspaceIdMultiAgenticSystemsMasIdConfigResponse503
    """

    return (
        await asyncio_detailed(
            ce_id=ce_id,
            workspace_id=workspace_id,
            mas_id=mas_id,
            client=client,
        )
    ).parsed
