from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cfn_concept_neighbors_api_cfn_knowledge_concepts_concept_id_neighbors_get_response_cfn_concept_neighbors_api_cfn_knowledge_concepts_concept_id_neighbors_get import (
    CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    concept_id: str,
    *,
    mas_id: str,
    workspace_id: None | str | Unset = UNSET,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["mas_id"] = mas_id

    json_workspace_id: None | str | Unset
    if isinstance(workspace_id, Unset):
        json_workspace_id = UNSET
    else:
        json_workspace_id = workspace_id
    params["workspace_id"] = json_workspace_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/cfn/knowledge/concepts/{concept_id}/neighbors".format(
            concept_id=quote(str(concept_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet
    | HTTPValidationError
    | None
):
    if response.status_code == 200:
        response_200 = CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet.from_dict(
            response.json()
        )

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
) -> Response[
    CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet
    | HTTPValidationError
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    concept_id: str,
    *,
    client: AuthenticatedClient | Client,
    mas_id: str,
    workspace_id: None | str | Unset = UNSET,
) -> Response[
    CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet
    | HTTPValidationError
]:
    """Cfn Concept Neighbors

     Fetch a concept's graph neighbors from CFN.

    Args:
        concept_id (str):
        mas_id (str):
        workspace_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        concept_id=concept_id,
        mas_id=mas_id,
        workspace_id=workspace_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    concept_id: str,
    *,
    client: AuthenticatedClient | Client,
    mas_id: str,
    workspace_id: None | str | Unset = UNSET,
) -> (
    CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet
    | HTTPValidationError
    | None
):
    """Cfn Concept Neighbors

     Fetch a concept's graph neighbors from CFN.

    Args:
        concept_id (str):
        mas_id (str):
        workspace_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet | HTTPValidationError
    """

    return sync_detailed(
        concept_id=concept_id,
        client=client,
        mas_id=mas_id,
        workspace_id=workspace_id,
    ).parsed


async def asyncio_detailed(
    concept_id: str,
    *,
    client: AuthenticatedClient | Client,
    mas_id: str,
    workspace_id: None | str | Unset = UNSET,
) -> Response[
    CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet
    | HTTPValidationError
]:
    """Cfn Concept Neighbors

     Fetch a concept's graph neighbors from CFN.

    Args:
        concept_id (str):
        mas_id (str):
        workspace_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        concept_id=concept_id,
        mas_id=mas_id,
        workspace_id=workspace_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    concept_id: str,
    *,
    client: AuthenticatedClient | Client,
    mas_id: str,
    workspace_id: None | str | Unset = UNSET,
) -> (
    CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet
    | HTTPValidationError
    | None
):
    """Cfn Concept Neighbors

     Fetch a concept's graph neighbors from CFN.

    Args:
        concept_id (str):
        mas_id (str):
        workspace_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGetResponseCfnConceptNeighborsApiCfnKnowledgeConceptsConceptIdNeighborsGet | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            concept_id=concept_id,
            client=client,
            mas_id=mas_id,
            workspace_id=workspace_id,
        )
    ).parsed
