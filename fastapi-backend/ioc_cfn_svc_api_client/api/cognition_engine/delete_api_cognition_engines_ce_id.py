from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.delete_api_cognition_engines_ce_id_response_400 import (
    DeleteApiCognitionEnginesCeIdResponse400,
)
from ...models.delete_api_cognition_engines_ce_id_response_404 import (
    DeleteApiCognitionEnginesCeIdResponse404,
)
from ...models.delete_api_cognition_engines_ce_id_response_502 import (
    DeleteApiCognitionEnginesCeIdResponse502,
)
from ...models.delete_api_cognition_engines_ce_id_response_503 import (
    DeleteApiCognitionEnginesCeIdResponse503,
)
from ...types import Response


def _get_kwargs(
    ce_id: str,
) -> dict[str, Any]:
    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/api/cognition-engines/{ce_id}".format(
            ce_id=quote(str(ce_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    Any
    | DeleteApiCognitionEnginesCeIdResponse400
    | DeleteApiCognitionEnginesCeIdResponse404
    | DeleteApiCognitionEnginesCeIdResponse502
    | DeleteApiCognitionEnginesCeIdResponse503
    | None
):
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

    if response.status_code == 400:
        response_400 = DeleteApiCognitionEnginesCeIdResponse400.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = DeleteApiCognitionEnginesCeIdResponse404.from_dict(response.json())

        return response_404

    if response.status_code == 502:
        response_502 = DeleteApiCognitionEnginesCeIdResponse502.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = DeleteApiCognitionEnginesCeIdResponse503.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    Any
    | DeleteApiCognitionEnginesCeIdResponse400
    | DeleteApiCognitionEnginesCeIdResponse404
    | DeleteApiCognitionEnginesCeIdResponse502
    | DeleteApiCognitionEnginesCeIdResponse503
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
    Any
    | DeleteApiCognitionEnginesCeIdResponse400
    | DeleteApiCognitionEnginesCeIdResponse404
    | DeleteApiCognitionEnginesCeIdResponse502
    | DeleteApiCognitionEnginesCeIdResponse503
]:
    """Delete Cognition Engine

     Soft-delete (deregister) a cognition engine by ID.

    Args:
        ce_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | DeleteApiCognitionEnginesCeIdResponse400 | DeleteApiCognitionEnginesCeIdResponse404 | DeleteApiCognitionEnginesCeIdResponse502 | DeleteApiCognitionEnginesCeIdResponse503]
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
    Any
    | DeleteApiCognitionEnginesCeIdResponse400
    | DeleteApiCognitionEnginesCeIdResponse404
    | DeleteApiCognitionEnginesCeIdResponse502
    | DeleteApiCognitionEnginesCeIdResponse503
    | None
):
    """Delete Cognition Engine

     Soft-delete (deregister) a cognition engine by ID.

    Args:
        ce_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | DeleteApiCognitionEnginesCeIdResponse400 | DeleteApiCognitionEnginesCeIdResponse404 | DeleteApiCognitionEnginesCeIdResponse502 | DeleteApiCognitionEnginesCeIdResponse503
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
    Any
    | DeleteApiCognitionEnginesCeIdResponse400
    | DeleteApiCognitionEnginesCeIdResponse404
    | DeleteApiCognitionEnginesCeIdResponse502
    | DeleteApiCognitionEnginesCeIdResponse503
]:
    """Delete Cognition Engine

     Soft-delete (deregister) a cognition engine by ID.

    Args:
        ce_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | DeleteApiCognitionEnginesCeIdResponse400 | DeleteApiCognitionEnginesCeIdResponse404 | DeleteApiCognitionEnginesCeIdResponse502 | DeleteApiCognitionEnginesCeIdResponse503]
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
    Any
    | DeleteApiCognitionEnginesCeIdResponse400
    | DeleteApiCognitionEnginesCeIdResponse404
    | DeleteApiCognitionEnginesCeIdResponse502
    | DeleteApiCognitionEnginesCeIdResponse503
    | None
):
    """Delete Cognition Engine

     Soft-delete (deregister) a cognition engine by ID.

    Args:
        ce_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | DeleteApiCognitionEnginesCeIdResponse400 | DeleteApiCognitionEnginesCeIdResponse404 | DeleteApiCognitionEnginesCeIdResponse502 | DeleteApiCognitionEnginesCeIdResponse503
    """

    return (
        await asyncio_detailed(
            ce_id=ce_id,
            client=client,
        )
    ).parsed
