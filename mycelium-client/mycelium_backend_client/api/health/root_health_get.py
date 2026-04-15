from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    check_llm: bool | Unset = False,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["check_llm"] = check_llm

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/health",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = response.json()
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
) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    check_llm: bool | Unset = False,
) -> Response[Any | HTTPValidationError]:
    """Root

     Health check.

    Pass ?check_llm=true to probe the LLM provider (zero-cost model-list call).
    Without it, only local config status is included.

    Args:
        check_llm (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        check_llm=check_llm,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    check_llm: bool | Unset = False,
) -> Any | HTTPValidationError | None:
    """Root

     Health check.

    Pass ?check_llm=true to probe the LLM provider (zero-cost model-list call).
    Without it, only local config status is included.

    Args:
        check_llm (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        check_llm=check_llm,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    check_llm: bool | Unset = False,
) -> Response[Any | HTTPValidationError]:
    """Root

     Health check.

    Pass ?check_llm=true to probe the LLM provider (zero-cost model-list call).
    Without it, only local config status is included.

    Args:
        check_llm (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        check_llm=check_llm,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    check_llm: bool | Unset = False,
) -> Any | HTTPValidationError | None:
    """Root

     Health check.

    Pass ?check_llm=true to probe the LLM provider (zero-cost model-list call).
    Without it, only local config status is included.

    Args:
        check_llm (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            check_llm=check_llm,
        )
    ).parsed
