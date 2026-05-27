from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.task_out import TaskOut
from ...models.task_toggle import TaskToggle
from ...types import UNSET, Response, Unset


def _get_kwargs(
    room_name: str,
    task_id: str,
    *,
    body: None | TaskToggle | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/rooms/{room_name}/plan/tasks/{task_id}/toggle".format(
            room_name=quote(str(room_name), safe=""),
            task_id=quote(str(task_id), safe=""),
        ),
    }

    if isinstance(body, TaskToggle):
        _kwargs["json"] = body.to_dict()
    else:
        _kwargs["json"] = body

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | TaskOut | None:
    if response.status_code == 200:
        response_200 = TaskOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | TaskOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    room_name: str,
    task_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: None | TaskToggle | Unset = UNSET,
) -> Response[HTTPValidationError | TaskOut]:
    """Toggle Task

    Args:
        room_name (str):
        task_id (str):
        body (None | TaskToggle | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | TaskOut]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        task_id=task_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    room_name: str,
    task_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: None | TaskToggle | Unset = UNSET,
) -> HTTPValidationError | TaskOut | None:
    """Toggle Task

    Args:
        room_name (str):
        task_id (str):
        body (None | TaskToggle | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | TaskOut
    """

    return sync_detailed(
        room_name=room_name,
        task_id=task_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    room_name: str,
    task_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: None | TaskToggle | Unset = UNSET,
) -> Response[HTTPValidationError | TaskOut]:
    """Toggle Task

    Args:
        room_name (str):
        task_id (str):
        body (None | TaskToggle | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | TaskOut]
    """

    kwargs = _get_kwargs(
        room_name=room_name,
        task_id=task_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    room_name: str,
    task_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: None | TaskToggle | Unset = UNSET,
) -> HTTPValidationError | TaskOut | None:
    """Toggle Task

    Args:
        room_name (str):
        task_id (str):
        body (None | TaskToggle | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | TaskOut
    """

    return (
        await asyncio_detailed(
            room_name=room_name,
            task_id=task_id,
            client=client,
            body=body,
        )
    ).parsed
