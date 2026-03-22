from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.audit_event_read import AuditEventRead
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    resource_type: None | str | Unset = UNSET,
    audit_type: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_resource_type: None | str | Unset
    if isinstance(resource_type, Unset):
        json_resource_type = UNSET
    else:
        json_resource_type = resource_type
    params["resource_type"] = json_resource_type

    json_audit_type: None | str | Unset
    if isinstance(audit_type, Unset):
        json_audit_type = UNSET
    else:
        json_audit_type = audit_type
    params["audit_type"] = json_audit_type

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/internal/audit-events",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[AuditEventRead] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = AuditEventRead.from_dict(response_200_item_data)

            response_200.append(response_200_item)

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
) -> Response[HTTPValidationError | list[AuditEventRead]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    resource_type: None | str | Unset = UNSET,
    audit_type: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | list[AuditEventRead]]:
    """List Audit Events

     List audit events with optional filters.

    Args:
        resource_type (None | str | Unset):
        audit_type (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[AuditEventRead]]
    """

    kwargs = _get_kwargs(
        resource_type=resource_type,
        audit_type=audit_type,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    resource_type: None | str | Unset = UNSET,
    audit_type: None | str | Unset = UNSET,
) -> HTTPValidationError | list[AuditEventRead] | None:
    """List Audit Events

     List audit events with optional filters.

    Args:
        resource_type (None | str | Unset):
        audit_type (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[AuditEventRead]
    """

    return sync_detailed(
        client=client,
        resource_type=resource_type,
        audit_type=audit_type,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    resource_type: None | str | Unset = UNSET,
    audit_type: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | list[AuditEventRead]]:
    """List Audit Events

     List audit events with optional filters.

    Args:
        resource_type (None | str | Unset):
        audit_type (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[AuditEventRead]]
    """

    kwargs = _get_kwargs(
        resource_type=resource_type,
        audit_type=audit_type,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    resource_type: None | str | Unset = UNSET,
    audit_type: None | str | Unset = UNSET,
) -> HTTPValidationError | list[AuditEventRead] | None:
    """List Audit Events

     List audit events with optional filters.

    Args:
        resource_type (None | str | Unset):
        audit_type (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[AuditEventRead]
    """

    return (
        await asyncio_detailed(
            client=client,
            resource_type=resource_type,
            audit_type=audit_type,
        )
    ).parsed
