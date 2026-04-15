from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cfn_list_api_cfn_knowledge_list_get_response_cfn_list_api_cfn_knowledge_list_get import (
    CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    mas_id: str,
    limit: int | Unset = 50,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["mas_id"] = mas_id

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/cfn/knowledge/list",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet.from_dict(response.json())

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
) -> Response[CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    mas_id: str,
    limit: int | Unset = 50,
) -> Response[CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError]:
    """Cfn List

     Enumerate nodes in CFN's AgensGraph for a given MAS.

    **Not a CFN API**. Goes around CFN's HTTP surface and queries the
    underlying AgensGraph directly, because CFN doesn't expose a list
    endpoint. Coupled to CFN's graph-naming convention
    (``graph_<mas_id_with_hyphens_underscored>``).

    Args:
        mas_id (str):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        mas_id=mas_id,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    mas_id: str,
    limit: int | Unset = 50,
) -> CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError | None:
    """Cfn List

     Enumerate nodes in CFN's AgensGraph for a given MAS.

    **Not a CFN API**. Goes around CFN's HTTP surface and queries the
    underlying AgensGraph directly, because CFN doesn't expose a list
    endpoint. Coupled to CFN's graph-naming convention
    (``graph_<mas_id_with_hyphens_underscored>``).

    Args:
        mas_id (str):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        mas_id=mas_id,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    mas_id: str,
    limit: int | Unset = 50,
) -> Response[CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError]:
    """Cfn List

     Enumerate nodes in CFN's AgensGraph for a given MAS.

    **Not a CFN API**. Goes around CFN's HTTP surface and queries the
    underlying AgensGraph directly, because CFN doesn't expose a list
    endpoint. Coupled to CFN's graph-naming convention
    (``graph_<mas_id_with_hyphens_underscored>``).

    Args:
        mas_id (str):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        mas_id=mas_id,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    mas_id: str,
    limit: int | Unset = 50,
) -> CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError | None:
    """Cfn List

     Enumerate nodes in CFN's AgensGraph for a given MAS.

    **Not a CFN API**. Goes around CFN's HTTP surface and queries the
    underlying AgensGraph directly, because CFN doesn't expose a list
    endpoint. Coupled to CFN's graph-naming convention
    (``graph_<mas_id_with_hyphens_underscored>``).

    Args:
        mas_id (str):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CfnListApiCfnKnowledgeListGetResponseCfnListApiCfnKnowledgeListGet | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            mas_id=mas_id,
            limit=limit,
        )
    ).parsed
