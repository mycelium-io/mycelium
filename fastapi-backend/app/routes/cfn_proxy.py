# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
CFN proxy endpoints.

Two concerns live here:

1. **Per-agent memory provider adapter**. ``memory_operations`` forwards
   arbitrary HTTP to an agent's ``memory_provider_url`` (from the agents
   table). Unrelated to CFN shared-memories. The URL shape
   (``/api/workspaces/{w}/multi-agentic-systems/{m}/agents/{a}/memory-operations``)
   is a stable public surface and is NOT touched by this PR.

2. **CFN shared-memories read surface**. Four routes under
   ``/api/cfn/knowledge/*`` that proxy through to CFN's query endpoints.
   These back the ``mycelium cfn query/concepts/neighbors/paths`` CLI
   commands so users can inspect what's in CFN's knowledge graph without
   tailing container logs. The corresponding CFN client functions live
   in ``app/services/cfn_knowledge.py``.
"""

import asyncio
import json
import logging
import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Agent, AuditEvent
from app.services.cfn_graph_read import CfnGraphUnavailable, list_concepts
from app.services.cfn_knowledge import (
    CfnKnowledgeError,
    get_concept_neighbors,
    get_concepts_by_ids,
    get_graph_paths,
    query_shared_memories,
)
from app.services.cfn_resolve import resolve_mas_id, resolve_workspace_id

logger = logging.getLogger(__name__)

# Per-agent memory adapter (stable, unrelated to CFN shared-memories).
router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}",
    tags=["cfn-proxy"],
)

# CFN shared-memories read surface — backs the `mycelium cfn` CLI commands.
cfn_read_router = APIRouter(prefix="/api/cfn/knowledge", tags=["cfn-read"])


async def _emit_audit(
    db: AsyncSession, audit_type: str, resource_type: str, resource_identifier: str
) -> None:
    nil_uuid = uuid_mod.UUID(int=0)
    now = datetime.now(UTC)
    event = AuditEvent(
        resource_type=resource_type,
        resource_identifier=resource_identifier,
        audit_type=audit_type,
        audit_resource_identifier=resource_identifier,
        created_by=nil_uuid,
        created_on=now,
        last_modified_by=nil_uuid,
        last_modified_on=now,
    )
    db.add(event)
    await db.commit()


# ── Per-agent memory adapter (unchanged) ────────────────────────────────────


async def _resolve_memory_provider_url(
    agent_id: UUID,
    db: AsyncSession,
) -> str:
    """Look up agent.memory_provider_url from DB; raise 404 if not found."""
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id!s} not found")

    if not agent.memory_provider_url:
        raise HTTPException(
            status_code=404, detail=f"agent {agent_id!s} has no memory_provider_url configured"
        )

    return agent.memory_provider_url.rstrip("/")


@router.post("/agents/{agent_id}/memory-operations")
async def memory_operations(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict:
    """Proxy an arbitrary HTTP request to an agent's memory provider.

    Request envelope:
        {"payload": {"http-request-type": "POST", "http-url": "/v1/memories",
                     "http-request-body": {...}, "http-headers": {...}}}

    Response envelope:
        {"http-status": 200, "http-headers": {...}, "http-response-body": {...}}
    """
    body = await request.json()
    payload = body.get("payload", {})

    method = payload.get("http-request-type", "").upper()
    if not method:
        raise HTTPException(status_code=400, detail="http-request-type is required")

    base_url = await _resolve_memory_provider_url(agent_id, db)

    path = payload.get("http-url", "")
    target = base_url + ("/" + path.lstrip("/") if path else "")

    req_body = payload.get("http-request-body")
    headers = dict(payload.get("http-headers") or {})
    if req_body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    logger.info("memory_operations %s %s", method, target)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method=method,
                url=target,
                json=req_body if req_body else None,
                headers=headers,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"memory provider unreachable: {exc}") from exc

    resp_headers: dict = dict(resp.headers)
    try:
        resp_body = resp.json()
    except json.JSONDecodeError:
        resp_body = {"raw": resp.text}

    try:
        await _emit_audit(db, "MEMORY_OPERATION", "MAS", str(mas_id))
    except SQLAlchemyError as exc:
        logger.warning("memory_operations: audit event failed: %s", exc)

    return {
        "http-status": resp.status_code,
        "http-headers": resp_headers,
        "http-response-body": resp_body,
    }


# ── CFN shared-memories read surface ────────────────────────────────────────


def _raise_from_cfn_error(exc: CfnKnowledgeError) -> None:
    code = exc.status_code or 502
    raise HTTPException(status_code=code, detail=str(exc))


class QueryRequest(BaseModel):
    intent: str
    mas_id: str | None = None
    workspace_id: str | None = None
    agent_id: str | None = None
    search_strategy: str = "semantic_graph_traversal"
    additional_context: dict[str, Any] | None = None


@cfn_read_router.post("/query")
async def cfn_query(
    data: QueryRequest,
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict[str, Any]:
    """Semantic-graph query against CFN's shared memory.

    CFN returns a natural-language answer from its evidence agent
    (``{"response_id": str, "message": str}``), not a structured record
    list. The ``mycelium cfn query`` CLI renders the message directly.
    """
    workspace_id = resolve_workspace_id(data.workspace_id)
    mas_id = await resolve_mas_id(data.mas_id, None, db)
    try:
        return await query_shared_memories(
            workspace_id=workspace_id,
            mas_id=mas_id,
            intent=data.intent,
            agent_id=data.agent_id,
            search_strategy=data.search_strategy,
            additional_context=data.additional_context,
        )
    except CfnKnowledgeError as exc:
        _raise_from_cfn_error(exc)
        raise  # unreachable, but keeps type checkers happy


class ConceptsByIdsRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1)
    mas_id: str | None = None
    workspace_id: str | None = None


@cfn_read_router.post("/concepts")
async def cfn_concepts_by_ids(
    data: ConceptsByIdsRequest,
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict[str, Any]:
    """Fetch CFN concept records by explicit IDs."""
    workspace_id = resolve_workspace_id(data.workspace_id)
    mas_id = await resolve_mas_id(data.mas_id, None, db)
    try:
        return await get_concepts_by_ids(
            workspace_id=workspace_id,
            mas_id=mas_id,
            ids=data.ids,
        )
    except CfnKnowledgeError as exc:
        _raise_from_cfn_error(exc)
        raise


@cfn_read_router.get("/concepts/{concept_id}/neighbors")
async def cfn_concept_neighbors(
    concept_id: str,
    db: Annotated[AsyncSession, Depends(get_async_session)],
    mas_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Fetch a concept's graph neighbors from CFN."""
    resolved_workspace = resolve_workspace_id(workspace_id)
    resolved_mas = await resolve_mas_id(mas_id, None, db)
    try:
        return await get_concept_neighbors(
            workspace_id=resolved_workspace,
            mas_id=resolved_mas,
            concept_id=concept_id,
        )
    except CfnKnowledgeError as exc:
        _raise_from_cfn_error(exc)
        raise


class GraphPathsRequest(BaseModel):
    source_id: str
    target_id: str
    mas_id: str | None = None
    workspace_id: str | None = None
    max_depth: int | None = None
    relations: list[str] | None = None
    limit: int | None = None


@cfn_read_router.post("/paths")
async def cfn_graph_paths(
    data: GraphPathsRequest,
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict[str, Any]:
    """Fetch paths between two CFN concepts by ID."""
    workspace_id = resolve_workspace_id(data.workspace_id)
    mas_id = await resolve_mas_id(data.mas_id, None, db)
    try:
        return await get_graph_paths(
            workspace_id=workspace_id,
            mas_id=mas_id,
            source_id=data.source_id,
            target_id=data.target_id,
            max_depth=data.max_depth,
            relations=data.relations,
            limit=data.limit,
        )
    except CfnKnowledgeError as exc:
        _raise_from_cfn_error(exc)
        raise


@cfn_read_router.get("/list")
async def cfn_list(
    db: Annotated[AsyncSession, Depends(get_async_session)],
    mas_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Enumerate nodes in CFN's AgensGraph for a given MAS.

    **Not a CFN API**. Goes around CFN's HTTP surface and queries the
    underlying AgensGraph directly, because CFN doesn't expose a list
    endpoint. Coupled to CFN's graph-naming convention
    (``graph_<mas_id_with_hyphens_underscored>``).
    """
    resolved_mas = await resolve_mas_id(mas_id, None, db)
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be 1..500")
    try:
        nodes = await asyncio.to_thread(list_concepts, mas_id=resolved_mas, limit=limit)
    except CfnGraphUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"mas_id": resolved_mas, "limit": limit, "count": len(nodes), "nodes": nodes}
