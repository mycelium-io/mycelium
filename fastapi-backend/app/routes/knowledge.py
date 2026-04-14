# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Knowledge graph endpoints.

POST   /api/knowledge/graphs        — store concepts/relations (legacy, C7 removes)
DELETE /api/knowledge/graphs        — delete concepts (legacy, C7 removes)
POST   /api/knowledge/graphs/query  — query graph (legacy, C7 removes)
POST   /api/knowledge/ingest        — forward openclaw turns to CFN shared-memories
DELETE /api/internal/knowledge/graphs — drop whole graph (legacy, C7 removes)
"""

import logging
import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.database import get_async_session
from app.knowledge import service
from app.knowledge.schemas import (
    KnowledgeGraphDeleteRequest,
    KnowledgeGraphQueryRequest,
    KnowledgeGraphStoreRequest,
    ResponseStatus,
)
from app.models import AuditEvent
from app.services.cfn_knowledge import (
    CfnKnowledgeError,
    create_or_update_shared_memories,
    estimate_cfn_knowledge_input_tokens,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["knowledge"])
internal_router = APIRouter(tags=["knowledge-internal"])


# ── Ingest schemas ─────────────────────────────────────────────────────────────


class KnowledgeIngestRequest(BaseModel):
    workspace_id: str
    mas_id: str
    agent_id: str | None = None
    records: list[dict]


class KnowledgeIngestResponse(BaseModel):
    cfn_response_id: str
    cfn_message: str | None = None
    ingested_at: datetime
    estimated_cfn_knowledge_input_tokens: int


@router.post("/api/knowledge/graphs")
def create_graph_store(data: KnowledgeGraphStoreRequest) -> JSONResponse:
    response = service.create_graph_store(data)
    if response.status == ResponseStatus.SUCCESS:
        code = status.HTTP_201_CREATED
    elif response.status == ResponseStatus.VALIDATION_ERROR:
        code = status.HTTP_400_BAD_REQUEST
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(content=response.model_dump(), status_code=code)


@router.delete("/api/knowledge/graphs")
def delete_graph_store(data: KnowledgeGraphDeleteRequest) -> JSONResponse:
    response = service.delete_graph_store(data)
    if response.status == ResponseStatus.SUCCESS:
        code = status.HTTP_200_OK
    elif response.status == ResponseStatus.VALIDATION_ERROR:
        code = status.HTTP_400_BAD_REQUEST
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(content=response.model_dump(), status_code=code)


@router.post("/api/knowledge/graphs/query")
def query_graph_store(data: KnowledgeGraphQueryRequest) -> JSONResponse:
    response = service.query_graph_store(data)
    if response.status == ResponseStatus.SUCCESS:
        code = status.HTTP_200_OK
    elif response.status == ResponseStatus.VALIDATION_ERROR:
        code = status.HTTP_400_BAD_REQUEST
    elif response.status == ResponseStatus.NOT_FOUND:
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(content=response.model_dump(), status_code=code)


@internal_router.delete("/api/internal/knowledge/graphs")
def internal_delete_graph(data: KnowledgeGraphDeleteRequest) -> JSONResponse:
    response = service.delete_graph_store_internal(data)
    if response.status == ResponseStatus.SUCCESS:
        code = status.HTTP_200_OK
    elif response.status == ResponseStatus.VALIDATION_ERROR:
        code = status.HTTP_400_BAD_REQUEST
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(content=response.model_dump(), status_code=code)


# ── Ingest ─────────────────────────────────────────────────────────────────────


@router.post("/api/knowledge/ingest", status_code=200)
async def knowledge_ingest(
    data: KnowledgeIngestRequest,
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> KnowledgeIngestResponse:
    """Forward openclaw turns to CFN's shared-memories endpoint.

    CFN runs concept + relationship extraction, embeddings, and KG writes
    inside its handler. We keep the durable ``KNOWLEDGE_INGESTION`` audit
    event and return the CFN response_id plus an input-side token estimate
    so ``mycelium cfn log`` / ``stats`` can surface cost to the user.
    """
    est_tokens = estimate_cfn_knowledge_input_tokens(data.records)

    try:
        cfn_resp = await create_or_update_shared_memories(
            workspace_id=data.workspace_id,
            mas_id=data.mas_id,
            records=data.records,
            agent_id=data.agent_id,
        )
    except CfnKnowledgeError as exc:
        code = exc.status_code or status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    try:
        nil_uuid = uuid_mod.UUID(int=0)
        now = datetime.now(UTC)
        event = AuditEvent(
            resource_type="MAS",
            resource_identifier=data.mas_id,
            audit_type="KNOWLEDGE_INGESTION",
            audit_resource_identifier=data.mas_id,
            created_by=nil_uuid,
            created_on=now,
            last_modified_by=nil_uuid,
            last_modified_on=now,
        )
        db.add(event)
        await db.commit()
    except SQLAlchemyError as exc:
        logger.warning("ingest: audit event failed: %s", exc)

    return KnowledgeIngestResponse(
        cfn_response_id=cfn_resp.get("response_id", ""),
        cfn_message=cfn_resp.get("message"),
        ingested_at=datetime.now(UTC),
        estimated_cfn_knowledge_input_tokens=est_tokens,
    )
