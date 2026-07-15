from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cognitionengine_cognition_engine_list import CognitionengineCognitionEngineList
from ...models.get_api_cognition_engines_response_502 import GetApiCognitionEnginesResponse502
from ...models.get_api_cognition_engines_response_503 import GetApiCognitionEnginesResponse503
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    cfn_id: str | Unset = UNSET,
    status: str | Unset = UNSET,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["cfn_id"] = cfn_id

    params["status"] = status

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/cognition-engines",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    CognitionengineCognitionEngineList
    | GetApiCognitionEnginesResponse502
    | GetApiCognitionEnginesResponse503
    | None
):
    if response.status_code == 200:
        response_200 = CognitionengineCognitionEngineList.from_dict(response.json())

        return response_200

    if response.status_code == 502:
        response_502 = GetApiCognitionEnginesResponse502.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = GetApiCognitionEnginesResponse503.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    CognitionengineCognitionEngineList
    | GetApiCognitionEnginesResponse502
    | GetApiCognitionEnginesResponse503
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
    cfn_id: str | Unset = UNSET,
    status: str | Unset = UNSET,
) -> Response[
    CognitionengineCognitionEngineList
    | GetApiCognitionEnginesResponse502
    | GetApiCognitionEnginesResponse503
]:
    """List Cognition Engines

     List cognition engines, optionally filtered by cfn_id and/or status.

    Args:
        cfn_id (str | Unset):
        status (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineCognitionEngineList | GetApiCognitionEnginesResponse502 | GetApiCognitionEnginesResponse503]
    """

    kwargs = _get_kwargs(
        cfn_id=cfn_id,
        status=status,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    cfn_id: str | Unset = UNSET,
    status: str | Unset = UNSET,
) -> (
    CognitionengineCognitionEngineList
    | GetApiCognitionEnginesResponse502
    | GetApiCognitionEnginesResponse503
    | None
):
    """List Cognition Engines

     List cognition engines, optionally filtered by cfn_id and/or status.

    Args:
        cfn_id (str | Unset):
        status (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineCognitionEngineList | GetApiCognitionEnginesResponse502 | GetApiCognitionEnginesResponse503
    """

    return sync_detailed(
        client=client,
        cfn_id=cfn_id,
        status=status,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    cfn_id: str | Unset = UNSET,
    status: str | Unset = UNSET,
) -> Response[
    CognitionengineCognitionEngineList
    | GetApiCognitionEnginesResponse502
    | GetApiCognitionEnginesResponse503
]:
    """List Cognition Engines

     List cognition engines, optionally filtered by cfn_id and/or status.

    Args:
        cfn_id (str | Unset):
        status (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CognitionengineCognitionEngineList | GetApiCognitionEnginesResponse502 | GetApiCognitionEnginesResponse503]
    """

    kwargs = _get_kwargs(
        cfn_id=cfn_id,
        status=status,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    cfn_id: str | Unset = UNSET,
    status: str | Unset = UNSET,
) -> (
    CognitionengineCognitionEngineList
    | GetApiCognitionEnginesResponse502
    | GetApiCognitionEnginesResponse503
    | None
):
    """List Cognition Engines

     List cognition engines, optionally filtered by cfn_id and/or status.

    Args:
        cfn_id (str | Unset):
        status (str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CognitionengineCognitionEngineList | GetApiCognitionEnginesResponse502 | GetApiCognitionEnginesResponse503
    """

    return (
        await asyncio_detailed(
            client=client,
            cfn_id=cfn_id,
            status=status,
        )
    ).parsed
