from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cognitionengine_cognition_engine_detail import CognitionengineCognitionEngineDetail
from ...models.cognitionengine_patch_request import CognitionenginePatchRequest
from ...models.patch_api_cognition_engines_ce_id_response_400 import (
    PatchApiCognitionEnginesCeIdResponse400,
)
from ...models.patch_api_cognition_engines_ce_id_response_404 import (
    PatchApiCognitionEnginesCeIdResponse404,
)
from ...models.patch_api_cognition_engines_ce_id_response_502 import (
    PatchApiCognitionEnginesCeIdResponse502,
)
from ...models.patch_api_cognition_engines_ce_id_response_503 import (
    PatchApiCognitionEnginesCeIdResponse503,
)
from ...types import Response


def _get_kwargs(
    ce_id: str,
    *,
    body: CognitionenginePatchRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/cognition-engines/{ce_id}".format(
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
    CognitionengineCognitionEngineDetail
    | PatchApiCognitionEnginesCeIdResponse400
    | PatchApiCognitionEnginesCeIdResponse404
    | PatchApiCognitionEnginesCeIdResponse502
    | PatchApiCognitionEnginesCeIdResponse503
    | None
):
    if response.status_code == 200:
        response_200 = CognitionengineCognitionEngineDetail.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = PatchApiCognitionEnginesCeIdResponse400.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = PatchApiCognitionEnginesCeIdResponse404.from_dict(response.json())

        return response_404

    if response.status_code == 502:
        response_502 = PatchApiCognitionEnginesCeIdResponse502.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = PatchApiCognitionEnginesCeIdResponse503.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    CognitionengineCognitionEngineDetail
    | PatchApiCognitionEnginesCeIdResponse400
    | PatchApiCognitionEnginesCeIdResponse404
    | PatchApiCognitionEnginesCeIdResponse502
    | PatchApiCognitionEnginesCeIdResponse503
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
    body: CognitionenginePatchRequest,
) -> Response[
    CognitionengineCognitionEngineDetail
    | PatchApiCognitionEnginesCeIdResponse400
    | PatchApiCognitionEnginesCeIdResponse404
    | PatchApiCognitionEnginesCeIdResponse502
    | PatchApiCognitionEnginesCeIdResponse503
]:
    """Partially update a Cognition Engine

     Update mutable fields of a CE: url, enabled, capabilities, metrics, config, mas_config, auth, kind,
    subkind.
    Immutable fields (cfn_id, version, name, auto_attach) cannot be updated and will return 400.

    Args:
        ce_id (str):
        body (CognitionenginePatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineCognitionEngineDetail | PatchApiCognitionEnginesCeIdResponse400 | PatchApiCognitionEnginesCeIdResponse404 | PatchApiCognitionEnginesCeIdResponse502 | PatchApiCognitionEnginesCeIdResponse503]
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
    body: CognitionenginePatchRequest,
) -> (
    CognitionengineCognitionEngineDetail
    | PatchApiCognitionEnginesCeIdResponse400
    | PatchApiCognitionEnginesCeIdResponse404
    | PatchApiCognitionEnginesCeIdResponse502
    | PatchApiCognitionEnginesCeIdResponse503
    | None
):
    """Partially update a Cognition Engine

     Update mutable fields of a CE: url, enabled, capabilities, metrics, config, mas_config, auth, kind,
    subkind.
    Immutable fields (cfn_id, version, name, auto_attach) cannot be updated and will return 400.

    Args:
        ce_id (str):
        body (CognitionenginePatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineCognitionEngineDetail | PatchApiCognitionEnginesCeIdResponse400 | PatchApiCognitionEnginesCeIdResponse404 | PatchApiCognitionEnginesCeIdResponse502 | PatchApiCognitionEnginesCeIdResponse503
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
    body: CognitionenginePatchRequest,
) -> Response[
    CognitionengineCognitionEngineDetail
    | PatchApiCognitionEnginesCeIdResponse400
    | PatchApiCognitionEnginesCeIdResponse404
    | PatchApiCognitionEnginesCeIdResponse502
    | PatchApiCognitionEnginesCeIdResponse503
]:
    """Partially update a Cognition Engine

     Update mutable fields of a CE: url, enabled, capabilities, metrics, config, mas_config, auth, kind,
    subkind.
    Immutable fields (cfn_id, version, name, auto_attach) cannot be updated and will return 400.

    Args:
        ce_id (str):
        body (CognitionenginePatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineCognitionEngineDetail | PatchApiCognitionEnginesCeIdResponse400 | PatchApiCognitionEnginesCeIdResponse404 | PatchApiCognitionEnginesCeIdResponse502 | PatchApiCognitionEnginesCeIdResponse503]
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
    body: CognitionenginePatchRequest,
) -> (
    CognitionengineCognitionEngineDetail
    | PatchApiCognitionEnginesCeIdResponse400
    | PatchApiCognitionEnginesCeIdResponse404
    | PatchApiCognitionEnginesCeIdResponse502
    | PatchApiCognitionEnginesCeIdResponse503
    | None
):
    """Partially update a Cognition Engine

     Update mutable fields of a CE: url, enabled, capabilities, metrics, config, mas_config, auth, kind,
    subkind.
    Immutable fields (cfn_id, version, name, auto_attach) cannot be updated and will return 400.

    Args:
        ce_id (str):
        body (CognitionenginePatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineCognitionEngineDetail | PatchApiCognitionEnginesCeIdResponse400 | PatchApiCognitionEnginesCeIdResponse404 | PatchApiCognitionEnginesCeIdResponse502 | PatchApiCognitionEnginesCeIdResponse503
    """

    return (
        await asyncio_detailed(
            ce_id=ce_id,
            client=client,
            body=body,
        )
    ).parsed
