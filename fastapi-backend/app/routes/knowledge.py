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

import json
import logging
import time
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.services.ingest_log_buffer import IngestEvent, get_buffer

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
    event and append a non-durable :class:`IngestEvent` to the in-memory
    buffer so ``mycelium cfn log`` / ``stats`` can surface cost and success
    signal without tailing backend logs.
    """
    buffer = get_buffer()
    request_id = str(uuid_mod.uuid4())
    est_tokens = estimate_cfn_knowledge_input_tokens(data.records)
    payload_bytes = len(json.dumps(data.records))
    started = time.perf_counter()

    try:
        cfn_resp = await create_or_update_shared_memories(
            workspace_id=data.workspace_id,
            mas_id=data.mas_id,
            records=data.records,
            agent_id=data.agent_id,
            request_id=request_id,
        )
    except CfnKnowledgeError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        buffer.append(
            IngestEvent(
                timestamp=datetime.now(UTC),
                workspace_id=data.workspace_id,
                mas_id=data.mas_id,
                agent_id=data.agent_id,
                request_id=request_id,
                record_count=len(data.records),
                payload_bytes=payload_bytes,
                estimated_cfn_knowledge_input_tokens=est_tokens,
                latency_ms=latency_ms,
                cfn_status=exc.status_code,
                error=str(exc),
            ),
        )
        code = exc.status_code or status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    latency_ms = (time.perf_counter() - started) * 1000
    cfn_message = cfn_resp.get("message")
    buffer.append(
        IngestEvent(
            timestamp=datetime.now(UTC),
            workspace_id=data.workspace_id,
            mas_id=data.mas_id,
            agent_id=data.agent_id,
            request_id=request_id,
            record_count=len(data.records),
            payload_bytes=payload_bytes,
            estimated_cfn_knowledge_input_tokens=est_tokens,
            latency_ms=latency_ms,
            cfn_status=status.HTTP_201_CREATED,
            cfn_message=cfn_message,
        ),
    )

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
        cfn_response_id=cfn_resp.get("response_id", request_id),
        cfn_message=cfn_message,
        ingested_at=datetime.now(UTC),
        estimated_cfn_knowledge_input_tokens=est_tokens,
    )


# ── Ingest observability (in-memory, resets on backend restart) ────────────────


class IngestLogResponse(BaseModel):
    buffer_started_at: datetime
    total_events: int
    events: list[IngestEvent]


class IngestStatsAggregate(BaseModel):
    events: int
    estimated_cfn_knowledge_input_tokens: int
    payload_bytes: int


class IngestStatsResponse(BaseModel):
    buffer_started_at: datetime
    last_event_at: datetime | None
    total: IngestStatsAggregate
    last_hour: IngestStatsAggregate
    by_mas: dict[str, IngestStatsAggregate]
    by_agent: dict[str, IngestStatsAggregate]


@router.get("/api/knowledge/ingest/log")
def knowledge_ingest_log(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> IngestLogResponse:
    """Return the most recent CFN shared-memories forward attempts.

    Newest first. Resets on backend restart. Captures both successes and
    failures; ``error`` is set on failures, ``cfn_message`` on successes.
    """
    buffer = get_buffer()
    events = buffer.snapshot()
    events.reverse()
    return IngestLogResponse(
        buffer_started_at=buffer.started_at,
        total_events=len(events),
        events=events[:limit],
    )


def _fresh_aggregate() -> dict[str, Any]:
    return {
        "events": 0,
        "estimated_cfn_knowledge_input_tokens": 0,
        "payload_bytes": 0,
    }


def _accumulate(agg: dict[str, Any], event: IngestEvent) -> None:
    agg["events"] += 1
    agg["estimated_cfn_knowledge_input_tokens"] += (
        event.estimated_cfn_knowledge_input_tokens
    )
    agg["payload_bytes"] += event.payload_bytes


@router.get("/api/knowledge/ingest/stats")
def knowledge_ingest_stats() -> IngestStatsResponse:
    """Aggregate CFN ingest activity across the current in-memory buffer.

    Grouped by ``mas_id`` and ``agent_id``. ``last_hour`` is a rolling window
    over the buffer. Buffer resets on backend restart, so these are
    process-lifetime numbers, not durable metrics.
    """
    buffer = get_buffer()
    events = buffer.snapshot()

    total = _fresh_aggregate()
    last_hour = _fresh_aggregate()
    by_mas: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}

    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)

    for event in events:
        _accumulate(total, event)
        if event.timestamp >= one_hour_ago:
            _accumulate(last_hour, event)
        _accumulate(by_mas.setdefault(event.mas_id, _fresh_aggregate()), event)
        agent_key = event.agent_id or "(none)"
        _accumulate(by_agent.setdefault(agent_key, _fresh_aggregate()), event)

    return IngestStatsResponse(
        buffer_started_at=buffer.started_at,
        last_event_at=events[-1].timestamp if events else None,
        total=IngestStatsAggregate(**total),
        last_hour=IngestStatsAggregate(**last_hour),
        by_mas={k: IngestStatsAggregate(**v) for k, v in by_mas.items()},
        by_agent={k: IngestStatsAggregate(**v) for k, v in by_agent.items()},
    )
