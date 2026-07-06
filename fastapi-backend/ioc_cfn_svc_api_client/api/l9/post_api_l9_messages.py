from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.l9l9 import L9L9
from ...models.post_api_l9_messages_response_400 import PostApiL9MessagesResponse400
from ...models.post_api_l9_messages_response_404 import PostApiL9MessagesResponse404
from ...models.post_api_l9_messages_response_500 import PostApiL9MessagesResponse500
from ...models.post_api_l9_messages_response_502 import PostApiL9MessagesResponse502
from ...models.post_api_l9_messages_response_503 import PostApiL9MessagesResponse503
from ...types import Response


def _get_kwargs(
    *,
    body: L9L9,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/l9/messages",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    L9L9
    | PostApiL9MessagesResponse400
    | PostApiL9MessagesResponse404
    | PostApiL9MessagesResponse500
    | PostApiL9MessagesResponse502
    | PostApiL9MessagesResponse503
    | None
):
    if response.status_code == 200:
        response_200 = L9L9.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = PostApiL9MessagesResponse400.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = PostApiL9MessagesResponse404.from_dict(response.json())

        return response_404

    if response.status_code == 500:
        response_500 = PostApiL9MessagesResponse500.from_dict(response.json())

        return response_500

    if response.status_code == 502:
        response_502 = PostApiL9MessagesResponse502.from_dict(response.json())

        return response_502

    if response.status_code == 503:
        response_503 = PostApiL9MessagesResponse503.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    L9L9
    | PostApiL9MessagesResponse400
    | PostApiL9MessagesResponse404
    | PostApiL9MessagesResponse500
    | PostApiL9MessagesResponse502
    | PostApiL9MessagesResponse503
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
    body: L9L9,
) -> Response[
    L9L9
    | PostApiL9MessagesResponse400
    | PostApiL9MessagesResponse404
    | PostApiL9MessagesResponse500
    | PostApiL9MessagesResponse502
    | PostApiL9MessagesResponse503
]:
    """Process and route L9 message to Cognition Engine

     Content-based routing: extracts workspace/MAS from L9 message participants.groups, selects CE by
    kind/subkind, forwards to CE's /api/l9/messages endpoint

    Args:
        body (L9L9):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[L9L9 | PostApiL9MessagesResponse400 | PostApiL9MessagesResponse404 | PostApiL9MessagesResponse500 | PostApiL9MessagesResponse502 | PostApiL9MessagesResponse503]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: L9L9,
) -> (
    L9L9
    | PostApiL9MessagesResponse400
    | PostApiL9MessagesResponse404
    | PostApiL9MessagesResponse500
    | PostApiL9MessagesResponse502
    | PostApiL9MessagesResponse503
    | None
):
    """Process and route L9 message to Cognition Engine

     Content-based routing: extracts workspace/MAS from L9 message participants.groups, selects CE by
    kind/subkind, forwards to CE's /api/l9/messages endpoint

    Args:
        body (L9L9):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        L9L9 | PostApiL9MessagesResponse400 | PostApiL9MessagesResponse404 | PostApiL9MessagesResponse500 | PostApiL9MessagesResponse502 | PostApiL9MessagesResponse503
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: L9L9,
) -> Response[
    L9L9
    | PostApiL9MessagesResponse400
    | PostApiL9MessagesResponse404
    | PostApiL9MessagesResponse500
    | PostApiL9MessagesResponse502
    | PostApiL9MessagesResponse503
]:
    """Process and route L9 message to Cognition Engine

     Content-based routing: extracts workspace/MAS from L9 message participants.groups, selects CE by
    kind/subkind, forwards to CE's /api/l9/messages endpoint

    Args:
        body (L9L9):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[L9L9 | PostApiL9MessagesResponse400 | PostApiL9MessagesResponse404 | PostApiL9MessagesResponse500 | PostApiL9MessagesResponse502 | PostApiL9MessagesResponse503]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: L9L9,
) -> (
    L9L9
    | PostApiL9MessagesResponse400
    | PostApiL9MessagesResponse404
    | PostApiL9MessagesResponse500
    | PostApiL9MessagesResponse502
    | PostApiL9MessagesResponse503
    | None
):
    """Process and route L9 message to Cognition Engine

     Content-based routing: extracts workspace/MAS from L9 message participants.groups, selects CE by
    kind/subkind, forwards to CE's /api/l9/messages endpoint

    Args:
        body (L9L9):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        L9L9 | PostApiL9MessagesResponse400 | PostApiL9MessagesResponse404 | PostApiL9MessagesResponse500 | PostApiL9MessagesResponse502 | PostApiL9MessagesResponse503
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
