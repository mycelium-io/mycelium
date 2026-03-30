"""
Knowledge graph endpoints.

POST   /api/knowledge/graphs        — store concepts/relations
DELETE /api/knowledge/graphs        — delete concepts (nodes)
POST   /api/knowledge/graphs/query  — query graph
POST   /api/knowledge/ingest        — ingest openclaw turns (two-stage LLM extraction)
DELETE /api/internal/knowledge/graphs — drop whole graph (internal)
"""

import logging
import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.config import settings
from app.database import get_async_session
from app.knowledge import service
from app.knowledge.ingestion import IngestionService
from app.knowledge.schemas import (
    KnowledgeGraphDeleteRequest,
    KnowledgeGraphQueryRequest,
    KnowledgeGraphStoreRequest,
    ResponseStatus,
)
from app.models import AuditEvent

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
    graph_name: str
    concepts_extracted: int
    relations_extracted: int


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
    """Ingest openclaw turns: two-stage LLM extraction → AgensGraph storage."""
    ingestion_svc = IngestionService(
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
    )

    try:
        result = await ingestion_svc.ingest(
            records=data.records,
            workspace_id=data.workspace_id,
            mas_id=data.mas_id,
            agent_id=data.agent_id,
        )
    except RuntimeError as exc:
        if "authentication failed" in str(exc).lower():
            return JSONResponse(
                status_code=503,
                content={"detail": str(exc)},
            )
        raise

    # Emit audit event (fire-and-forget, non-fatal)
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

    return KnowledgeIngestResponse(**result)
