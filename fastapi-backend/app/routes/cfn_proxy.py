"""
CFN proxy endpoints.

POST /api/workspaces/{wId}/multi-agentic-systems/{masId}/shared-memories
  → calls local knowledge graph service directly (no HTTP hop)

POST /api/workspaces/{wId}/multi-agentic-systems/{masId}/shared-memories/query
  → calls local knowledge graph service directly (no HTTP hop)

POST /api/workspaces/{wId}/multi-agentic-systems/{masId}/agents/{agentId}/memory-operations
  → forwards arbitrary HTTP to agent's memory_provider_url (from agents table)
"""

import json
import logging
import uuid as uuid_mod
from datetime import UTC
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.knowledge import service as kg_service
from app.knowledge.schemas import (
    KnowledgeGraphQueryRequest,
    KnowledgeGraphStoreRequest,
    ResponseStatus,
)
from app.models import MAS, Agent, AuditEvent, Workspace

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}",
    tags=["cfn-proxy"],
)


async def _emit_audit(db: AsyncSession, audit_type: str, resource_type: str, resource_identifier: str) -> None:
    from datetime import datetime
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


async def _resolve_memory_provider_url(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    db: AsyncSession,
) -> str:
    """Look up agent.memory_provider_url from DB; raise 404 if not found."""
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"workspace {workspace_id!s} not found")

    mas = await db.get(MAS, mas_id)
    if mas is None or mas.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"MAS {mas_id!s} not found")

    agent = await db.get(Agent, agent_id)
    if agent is None or agent.mas_id != mas_id:
        raise HTTPException(status_code=404, detail=f"agent {agent_id!s} not found")

    if not agent.memory_provider_url:
        raise HTTPException(status_code=404, detail=f"agent {agent_id!s} has no memory_provider_url configured")

    return agent.memory_provider_url.rstrip("/")


@router.post("/shared-memories", status_code=201)
async def upsert_shared_memories(
    workspace_id: UUID,
    mas_id: UUID,
    request: Request,
) -> JSONResponse:
    """Store shared memory concepts/relations directly into AgensGraph."""
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    if not isinstance(body, dict):
        body = {}

    # Inject mas_id / wksp_id from the URL path so callers don't need to repeat them
    body.setdefault("mas_id", str(mas_id))
    body.setdefault("wksp_id", str(workspace_id))

    try:
        store_req = KnowledgeGraphStoreRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("upsert_shared_memories workspace=%s mas=%s", workspace_id, mas_id)
    response = kg_service.create_graph_store(store_req)

    if response.status == ResponseStatus.SUCCESS:
        return JSONResponse(status_code=201, content=response.model_dump())
    if response.status == ResponseStatus.VALIDATION_ERROR:
        return JSONResponse(status_code=400, content=response.model_dump())
    return JSONResponse(status_code=500, content=response.model_dump())


@router.post("/shared-memories/query")
async def fetch_shared_memories(
    workspace_id: UUID,
    mas_id: UUID,
    request: Request,
) -> JSONResponse:
    """Query shared memory graph directly from AgensGraph."""
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    if not isinstance(body, dict):
        body = {}

    body.setdefault("mas_id", str(mas_id))
    body.setdefault("wksp_id", str(workspace_id))

    try:
        query_req = KnowledgeGraphQueryRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("fetch_shared_memories workspace=%s mas=%s", workspace_id, mas_id)
    response = kg_service.query_graph_store(query_req)

    if response.status == ResponseStatus.SUCCESS:
        return JSONResponse(status_code=200, content=response.model_dump())
    if response.status in (ResponseStatus.VALIDATION_ERROR,):
        return JSONResponse(status_code=400, content=response.model_dump())
    if response.status == ResponseStatus.NOT_FOUND:
        return JSONResponse(status_code=404, content=response.model_dump())
    return JSONResponse(status_code=500, content=response.model_dump())


@router.post("/agents/{agent_id}/memory-operations")
async def memory_operations(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict:
    """
    Proxy an arbitrary HTTP request to an agent's memory provider.

    Request envelope:
        {"payload": {"http-request-type": "POST", "http-url": "/v1/memories", "http-request-body": {...}, "http-headers": {...}}}

    Response envelope:
        {"http-status": 200, "http-headers": {...}, "http-response-body": {...}}
    """
    body = await request.json()
    payload = body.get("payload", {})

    method = payload.get("http-request-type", "").upper()
    if not method:
        raise HTTPException(status_code=400, detail="http-request-type is required")

    base_url = await _resolve_memory_provider_url(workspace_id, mas_id, agent_id, db)

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

    # Emit audit event (fire-and-forget, non-fatal)
    try:
        await _emit_audit(db, "MEMORY_OPERATION", "MAS", str(mas_id))
    except SQLAlchemyError as exc:
        logger.warning("memory_operations: audit event failed: %s", exc)

    return {
        "http-status": resp.status_code,
        "http-headers": resp_headers,
        "http-response-body": resp_body,
    }
