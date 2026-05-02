# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Async client for CFN's shared-memories knowledge API.

The ioc-cognition-fabric-node-svc (CFN) exposes shared-memories endpoints under
``/api/workspaces/{ws}/multi-agentic-systems/{mas}/``:

  POST  shared-memories              create/update knowledge   (typed client)
  POST  shared-memories/query        semantic query             (typed client)
  GET   graph/neighbors/{id}         graph neighbors            (raw httpx — not in schema)
  POST  graph/concepts/by_ids        concepts by id             (raw httpx — not in schema)
  POST  graph/paths                  graph paths                (raw httpx — not in schema)

The shared-memories endpoints go through ``ioc_cfn_svc_api_client`` so ty
catches breaking field changes when the client is regenerated. The graph/*
endpoints are flagged ``include_in_schema=False`` upstream and aren't in the
OpenAPI doc, so they remain on raw httpx.

CFN runs the heavy work (two-stage LLM extraction via ioc-cfn-cognitive-engines'
ingestion agent, embeddings, KG writes) inside the handler, so timeouts are
generous. Errors are raised as :class:`CfnKnowledgeError`; the route handler is
responsible for appending attempt records to the ingest log buffer and
translating failures to client-facing HTTP statuses.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx
import tiktoken

from app.config import settings
from app.services.metrics import record_cfn_call, record_knowledge_query
from ioc_cfn_svc_api_client import Client
from ioc_cfn_svc_api_client.api.shared_memories import (
    create_or_update_shared_memories_api_workspaces_workspace_id_multi_agentic_systems_mas_id_shared_memories_post as create_api,
)
from ioc_cfn_svc_api_client.api.shared_memories import (
    fetch_shared_memories_api_workspaces_workspace_id_multi_agentic_systems_mas_id_shared_memories_query_post as query_api,
)
from ioc_cfn_svc_api_client.errors import UnexpectedStatus
from ioc_cfn_svc_api_client.models import (
    CreateOrUpdateRequest,
    CreateOrUpdateResponse,
    ExtractionPayload,
    ExtractionPayloadDataItem,
    ExtractionPayloadMetadata,
    ExtractionPayloadMetadataFormat,
    Header,
    HTTPValidationError,
    QueryRequest,
    QueryRequestAdditionalContextType0,
    QueryResponse,
)

logger = logging.getLogger(__name__)

# Cached once at module load. tiktoken ships with litellm so no new dep.
_CL100K = tiktoken.get_encoding("cl100k_base")


def estimate_cfn_knowledge_input_tokens(records: list[dict[str, Any]]) -> int:
    """Input-side proxy for the LLM cost CFN will pay on these records.

    Encodes the JSON-serialized ``records`` with ``cl100k_base``. CFN's actual
    LLM consumption (system prompts, two-pass concept+relation extraction,
    embeddings) is typically higher; this is a cost-awareness signal, not a
    billing figure.
    """
    return len(_CL100K.encode(json.dumps(records)))


# CFN shared-memories runs concept + relationship LLM extraction plus
# embeddings. Match cfn_negotiation.py's 300s ceiling.
_CFN_HTTP_TIMEOUT = httpx.Timeout(300.0)


class CfnKnowledgeError(RuntimeError):
    """Raised when a CFN shared-memories request fails.

    ``status_code`` is set when the failure came from a non-2xx HTTP response;
    it is ``None`` for transport-level failures (timeout, connection refused).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _client() -> Client:
    return Client(
        base_url=settings.COGNITION_FABRIC_NODE_URL or "",
        timeout=_CFN_HTTP_TIMEOUT,
        raise_on_unexpected_status=True,
    )


def _mas_base(workspace_id: str, mas_id: str) -> str:
    """For graph/* endpoints not in the OpenAPI schema."""
    return (
        f"{settings.COGNITION_FABRIC_NODE_URL}"
        f"/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}"
    )


def _build_extraction_payload(records: list[dict[str, Any]]) -> ExtractionPayload:
    metadata = ExtractionPayloadMetadata(format_=ExtractionPayloadMetadataFormat.OPENCLAW)
    data_items: list[ExtractionPayloadDataItem] = []
    for record in records:
        item = ExtractionPayloadDataItem()
        for key, value in record.items():
            item[key] = value
        data_items.append(item)
    return ExtractionPayload(metadata=metadata, data=data_items)


async def create_or_update_shared_memories(
    *,
    workspace_id: str,
    mas_id: str,
    records: list[dict[str, Any]],
    agent_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """POST openclaw turns to CFN's ``shared-memories`` create/update endpoint.

    Builds a ``CreateOrUpdateRequest`` body with ``metadata.format="openclaw"``
    and the provided ``records`` as ``payload.data``. Returns CFN's response as
    a dict, typically ``{"response_id": str, "message": str | None}``.

    Raises :class:`CfnKnowledgeError` on any HTTP or transport failure.
    """
    body = CreateOrUpdateRequest(
        payload=_build_extraction_payload(records),
        header=Header(agent_id=agent_id) if agent_id else Header(),
        request_id=request_id or str(uuid.uuid4()),
    )
    t0 = time.monotonic()
    try:
        async with _client() as client:
            result = await create_api.asyncio(
                workspace_id=workspace_id,
                mas_id=mas_id,
                client=client,
                body=body,
            )
    except UnexpectedStatus as exc:
        record_cfn_call(
            service="node",
            operation="shared_memories",
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=exc.status_code,
            error=True,
        )
        raise _wrap_unexpected_status(exc, "shared-memories") from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.exception("CFN shared-memories unreachable")
        record_cfn_call(
            service="node",
            operation="shared_memories",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise CfnKnowledgeError(f"CFN unreachable: {exc}") from exc

    record_cfn_call(
        service="node",
        operation="shared_memories",
        duration_ms=(time.monotonic() - t0) * 1000,
    )

    if isinstance(result, HTTPValidationError):
        raise CfnKnowledgeError(
            f"CFN shared-memories validation error: {result.detail}",
            status_code=422,
        )
    if not isinstance(result, CreateOrUpdateResponse):
        raise CfnKnowledgeError(
            f"CFN shared-memories returned unexpected payload: {type(result).__name__}",
        )
    return result.to_dict()


async def query_shared_memories(
    *,
    workspace_id: str,
    mas_id: str,
    intent: str,
    agent_id: str | None = None,
    search_strategy: str = "semantic_graph_traversal",
    additional_context: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """POST to CFN's ``shared-memories/query`` endpoint.

    Returns CFN's QueryResponse dict: ``{"response_id": str, "message": str}``.
    Note that ``message`` is a natural-language answer synthesized by CFN's
    evidence agent, NOT a structured list of records.
    """
    ctx = QueryRequestAdditionalContextType0()
    if additional_context:
        for key, value in additional_context.items():
            ctx[key] = value
    body = QueryRequest(
        intent=intent,
        header=Header(agent_id=agent_id) if agent_id else Header(),
        request_id=request_id or str(uuid.uuid4()),
        search_strategy=search_strategy,
        additional_context=ctx if additional_context else None,
    )
    t0 = time.monotonic()
    try:
        async with _client() as client:
            result = await query_api.asyncio(
                workspace_id=workspace_id,
                mas_id=mas_id,
                client=client,
                body=body,
            )
    except UnexpectedStatus as exc:
        record_knowledge_query(
            query_type="semantic",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise _wrap_unexpected_status(exc, "shared-memories/query") from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.exception("CFN shared-memories/query unreachable")
        record_knowledge_query(
            query_type="semantic",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise CfnKnowledgeError(f"CFN unreachable: {exc}") from exc

    if isinstance(result, HTTPValidationError):
        raise CfnKnowledgeError(
            f"CFN shared-memories/query validation error: {result.detail}",
            status_code=422,
        )
    if not isinstance(result, QueryResponse):
        raise CfnKnowledgeError(
            f"CFN shared-memories/query returned unexpected payload: {type(result).__name__}",
        )
    resp = result.to_dict()
    record_knowledge_query(
        query_type="semantic",
        results_returned=1 if resp.get("message") else 0,
        duration_ms=(time.monotonic() - t0) * 1000,
    )
    return resp


def _wrap_unexpected_status(exc: UnexpectedStatus, endpoint: str) -> CfnKnowledgeError:
    snippet = exc.content[:300].decode("utf-8", errors="replace")
    logger.warning("CFN %s failed | status=%d body=%r", endpoint, exc.status_code, snippet)
    return CfnKnowledgeError(
        f"CFN {endpoint} returned {exc.status_code}: {snippet[:200]}",
        status_code=exc.status_code,
    )


# ── Graph read surface (raw httpx — not in CFN OpenAPI schema) ───────────────
#
# The graph/* endpoints are flagged ``include_in_schema=False`` upstream, so
# their shapes may drift — treat them as best-effort and don't rely on CFN's
# typed contract here.


async def _cfn_get(url: str, *, operation: str) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_CFN_HTTP_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            record_cfn_call(
                service="node",
                operation=operation,
                duration_ms=(time.monotonic() - t0) * 1000,
                status_code=resp.status_code,
            )
            return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        snippet = exc.response.text[:300]
        logger.warning("CFN GET failed | url=%s status=%d body=%r", url, status, snippet)
        record_cfn_call(
            service="node",
            operation=operation,
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=status,
            error=True,
        )
        raise CfnKnowledgeError(
            f"CFN GET {url} returned {status}: {snippet[:200]}",
            status_code=status,
        ) from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.exception("CFN GET unreachable | url=%s", url)
        record_cfn_call(
            service="node",
            operation=operation,
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise CfnKnowledgeError(f"CFN unreachable: {exc}") from exc


async def _cfn_post(url: str, body: dict[str, Any], *, operation: str) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_CFN_HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            record_cfn_call(
                service="node",
                operation=operation,
                duration_ms=(time.monotonic() - t0) * 1000,
                status_code=resp.status_code,
            )
            return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        snippet = exc.response.text[:300]
        # Identify the known Apache AGE concurrent-writer race (surfaces as
        # ``unrecognized heap_update status: 4`` from inside a Cypher
        # ``MATCH ... DETACH DELETE`` during shared-memory upsert). It's an
        # upstream bug in ioc-knowledge-memory's agensgraph layer, not a
        # Mycelium fault, but the write *did* fail so we still record it as
        # an error — just tag the log so it's grep-able and doesn't get
        # confused with timeouts or auth issues. See node.py:119 in
        # ioc-knowledge-memory.
        if "heap_update status" in snippet:
            logger.warning(
                "CFN POST failed | url=%s status=%d cause=age-concurrent-writer-race "
                "(upstream ioc-knowledge-memory AGE bug, see "
                "cfn_component_metrics_reconciliation.md)",
                url, status,
            )
        else:
            logger.warning("CFN POST failed | url=%s status=%d body=%r", url, status, snippet)
        record_cfn_call(
            service="node",
            operation=operation,
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=status,
            error=True,
        )
        raise CfnKnowledgeError(
            f"CFN POST {url} returned {status}: {snippet[:200]}",
            status_code=status,
        ) from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.exception("CFN POST unreachable | url=%s", url)
        record_cfn_call(
            service="node",
            operation=operation,
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise CfnKnowledgeError(f"CFN unreachable: {exc}") from exc


async def get_concepts_by_ids(
    *,
    workspace_id: str,
    mas_id: str,
    ids: list[str],
) -> dict[str, Any]:
    """POST to CFN's ``graph/concepts/by_ids`` endpoint.

    Returns CFN's ConceptsByIdsResponse dict with a ``records`` list.
    """
    url = f"{_mas_base(workspace_id, mas_id)}/graph/concepts/by_ids"
    t0 = time.monotonic()
    try:
        result = await _cfn_post(url, {"ids": ids}, operation="concepts_by_ids")
    except CfnKnowledgeError:
        record_knowledge_query(
            query_type="concept",
            nodes_queried=len(ids),
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise
    records = result.get("records", [])
    record_knowledge_query(
        query_type="concept",
        nodes_queried=len(ids),
        results_returned=len(records) if isinstance(records, list) else 0,
        duration_ms=(time.monotonic() - t0) * 1000,
    )
    return result


async def get_concept_neighbors(
    *,
    workspace_id: str,
    mas_id: str,
    concept_id: str,
) -> dict[str, Any]:
    """GET CFN's ``graph/neighbors/{concept_id}`` endpoint.

    Returns CFN's NeighborsResponse dict with a ``records`` list.
    """
    url = f"{_mas_base(workspace_id, mas_id)}/graph/neighbors/{concept_id}"
    t0 = time.monotonic()
    try:
        result = await _cfn_get(url, operation="neighbors")
    except CfnKnowledgeError:
        record_knowledge_query(
            query_type="neighbour",
            nodes_queried=1,
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise
    records = result.get("records", [])
    record_knowledge_query(
        query_type="neighbour",
        nodes_queried=1,
        results_returned=len(records) if isinstance(records, list) else 0,
        duration_ms=(time.monotonic() - t0) * 1000,
    )
    return result


async def get_graph_paths(
    *,
    workspace_id: str,
    mas_id: str,
    source_id: str,
    target_id: str,
    max_depth: int | None = None,
    relations: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """POST to CFN's ``graph/paths`` endpoint.

    Returns CFN's GraphPathsResponse dict with a ``paths`` list.
    """
    url = f"{_mas_base(workspace_id, mas_id)}/graph/paths"
    body: dict[str, Any] = {"source_id": source_id, "target_id": target_id}
    if max_depth is not None:
        body["max_depth"] = max_depth
    if relations:
        body["relations"] = relations
    if limit is not None:
        body["limit"] = limit
    t0 = time.monotonic()
    try:
        result = await _cfn_post(url, body, operation="graph_paths")
    except CfnKnowledgeError:
        record_knowledge_query(
            query_type="path",
            nodes_queried=2,
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise
    paths = result.get("paths", [])
    record_knowledge_query(
        query_type="path",
        nodes_queried=2,
        results_returned=len(paths) if isinstance(paths, list) else 0,
        duration_ms=(time.monotonic() - t0) * 1000,
    )
    return result
