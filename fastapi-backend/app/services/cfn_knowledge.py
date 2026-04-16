# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Async httpx client for CFN's shared-memories knowledge API.

The ioc-cognition-fabric-node-svc (CFN) exposes shared-memories endpoints under
``/api/workspaces/{ws}/multi-agentic-systems/{mas}/``:

  POST  shared-memories              create/update knowledge (this module)
  POST  shared-memories/query        semantic query            (C5)
  GET   graph/neighbors/{id}         graph neighbors           (C5)
  POST  graph/concepts/by_ids        concepts by id            (C5)
  POST  graph/paths                  graph paths               (C5)

CFN runs the heavy work (two-stage LLM extraction via ioc-cfn-cognitive-engines'
ingestion agent, embeddings, KG writes) inside the handler, so timeouts are
generous. Errors are raised as :class:`CfnKnowledgeError`; the route handler is
responsible for appending attempt records to the ingest log buffer and
translating failures to client-facing HTTP statuses.
"""

import json
import logging
import time
import uuid
from typing import Any

import httpx
import tiktoken

from app.config import settings
from app.services.metrics import record_cfn_call, record_knowledge_query

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


def _mas_base(workspace_id: str, mas_id: str) -> str:
    return (
        f"{settings.COGNITION_FABRIC_NODE_URL}"
        f"/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}"
    )


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
    url = f"{_mas_base(workspace_id, mas_id)}/shared-memories"
    rid = request_id or str(uuid.uuid4())
    body: dict[str, Any] = {
        "request_id": rid,
        "payload": {
            "metadata": {"format": "openclaw"},
            "data": records,
        },
    }
    if agent_id:
        body["header"] = {"agent_id": agent_id}
    return await _cfn_post(url, body, operation="shared_memories")


# ── Read surface ─────────────────────────────────────────────────────────────
#
# CFN's shared-memories read endpoints. These power the `mycelium cfn query /
# concepts / neighbors / paths` CLI subcommands. The graph/* endpoints are
# flagged include_in_schema=False upstream, so their shapes may drift — treat
# them as best-effort and catch ValidationError on response shape if we ever
# parse them structurally.


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
    url = f"{_mas_base(workspace_id, mas_id)}/shared-memories/query"
    body: dict[str, Any] = {
        "request_id": request_id or str(uuid.uuid4()),
        "intent": intent,
        "search_strategy": search_strategy,
    }
    if agent_id:
        body["header"] = {"agent_id": agent_id}
    if additional_context:
        body["additional_context"] = additional_context
    t0 = time.monotonic()
    try:
        result = await _cfn_post(url, body, operation="shared_memories_query")
    except CfnKnowledgeError:
        record_knowledge_query(
            query_type="semantic",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise
    record_knowledge_query(
        query_type="semantic",
        results_returned=1 if result.get("message") else 0,
        duration_ms=(time.monotonic() - t0) * 1000,
    )
    return result


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
