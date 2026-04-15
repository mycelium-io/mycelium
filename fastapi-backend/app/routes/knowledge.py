# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Knowledge graph endpoints.

POST /api/knowledge/ingest forwards openclaw turns to CFN's shared-memories
endpoint with user-configurable gates (enabled / token circuit breaker /
content-hash dedupe) and records each attempt in an in-memory observability
buffer surfaced via GET /log and GET /stats.
"""

import json
import logging
import time
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.config import settings
from app.database import get_async_session
from app.models import AuditEvent
from app.services.cfn_knowledge import (
    CfnKnowledgeError,
    create_or_update_shared_memories,
    estimate_cfn_knowledge_input_tokens,
)
from app.services.ingest_dedupe import get_cache
from app.services.ingest_log_buffer import IngestEvent, IngestState, get_buffer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["knowledge"])


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


# ── Ingest ─────────────────────────────────────────────────────────────────────


def _log_ingest_event(
    *,
    data: KnowledgeIngestRequest,
    request_id: str,
    est_tokens: int,
    payload_bytes: int,
    latency_ms: float,
    state: IngestState,
    reason: str | None = None,
    cfn_status: int | None = None,
    cfn_message: str | None = None,
) -> None:
    get_buffer().append(
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
            state=state,
            reason=reason,
            cfn_status=cfn_status,
            cfn_message=cfn_message,
        ),
    )


def _write_audit_event(db: AsyncSession, mas_id: str) -> "datetime":
    """Emit the durable KNOWLEDGE_INGESTION audit event. Caller must await commit."""
    now = datetime.now(UTC)
    nil_uuid = uuid_mod.UUID(int=0)
    db.add(
        AuditEvent(
            resource_type="MAS",
            resource_identifier=mas_id,
            audit_type="KNOWLEDGE_INGESTION",
            audit_resource_identifier=mas_id,
            created_by=nil_uuid,
            created_on=now,
            last_modified_by=nil_uuid,
            last_modified_on=now,
        ),
    )
    return now


@router.post("/api/knowledge/ingest", status_code=200)
async def knowledge_ingest(
    data: KnowledgeIngestRequest,
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> KnowledgeIngestResponse:
    """Forward openclaw turns to CFN's shared-memories endpoint.

    Enforces user-configured gates before hitting CFN:

    1. ``MYCELIUM_INGEST_ENABLED`` master switch — accept+discard when false.
    2. ``MYCELIUM_INGEST_MAX_INPUT_TOKENS`` circuit breaker — refuse with
       HTTP 413 when the estimated input exceeds the threshold.
    3. Content-hash dedupe cache — short-circuit duplicate payloads within
       ``MYCELIUM_INGEST_DEDUPE_TTL_SECONDS`` and return the cached
       ``response_id`` without re-hitting CFN.

    Every outcome is appended to the in-memory ingest log buffer so
    ``mycelium cfn log`` / ``stats`` can surface cost and success signal.
    The durable ``KNOWLEDGE_INGESTION`` audit event is still emitted for
    every accepted attempt (ok, deduped, disabled) — it stays as the
    tamper-evident record and is unaffected by the in-memory buffer.
    """
    request_id = str(uuid_mod.uuid4())
    est_tokens = estimate_cfn_knowledge_input_tokens(data.records)
    payload_bytes = len(json.dumps(data.records))
    started = time.perf_counter()

    # ── Gate 1: master kill switch ────────────────────────────────────────────
    if not settings.MYCELIUM_INGEST_ENABLED:
        _log_ingest_event(
            data=data,
            request_id=request_id,
            est_tokens=est_tokens,
            payload_bytes=payload_bytes,
            latency_ms=(time.perf_counter() - started) * 1000,
            state="disabled",
            reason="MYCELIUM_INGEST_ENABLED=false",
        )
        _write_audit_event(db, data.mas_id)
        try:
            await db.commit()
        except SQLAlchemyError as exc:
            logger.warning("ingest: audit event failed: %s", exc)
        return KnowledgeIngestResponse(
            cfn_response_id=request_id,
            cfn_message="ingest disabled via MYCELIUM_INGEST_ENABLED=false",
            ingested_at=datetime.now(UTC),
            estimated_cfn_knowledge_input_tokens=est_tokens,
        )

    # ── Gate 2: token circuit breaker ─────────────────────────────────────────
    max_tokens = settings.MYCELIUM_INGEST_MAX_INPUT_TOKENS
    if max_tokens > 0 and est_tokens > max_tokens:
        reason = f"payload exceeded {max_tokens} estimated input tokens (actual: {est_tokens})"
        _log_ingest_event(
            data=data,
            request_id=request_id,
            est_tokens=est_tokens,
            payload_bytes=payload_bytes,
            latency_ms=(time.perf_counter() - started) * 1000,
            state="refused",
            reason=reason,
        )
        logger.warning(
            "ingest refused | mas=%s agent=%s request_id=%s reason=%s",
            data.mas_id,
            data.agent_id,
            request_id,
            reason,
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=reason,
        )

    # ── Gate 3: content-hash dedupe ───────────────────────────────────────────
    cache = get_cache()
    ttl = settings.MYCELIUM_INGEST_DEDUPE_TTL_SECONDS
    content_hash = cache.hash_records(data.records) if ttl > 0 else ""
    cached = cache.lookup(content_hash) if content_hash else None
    if cached is not None:
        _log_ingest_event(
            data=data,
            request_id=request_id,
            est_tokens=est_tokens,
            payload_bytes=payload_bytes,
            latency_ms=(time.perf_counter() - started) * 1000,
            state="deduped",
            reason=f"hash match within {ttl}s TTL",
            cfn_message=cached.message,
        )
        # Durable audit — deduped still represents a "we accepted this" event.
        _write_audit_event(db, data.mas_id)
        try:
            await db.commit()
        except SQLAlchemyError as exc:
            logger.warning("ingest: audit event failed: %s", exc)
        return KnowledgeIngestResponse(
            cfn_response_id=cached.response_id,
            cfn_message=cached.message,
            ingested_at=datetime.now(UTC),
            estimated_cfn_knowledge_input_tokens=est_tokens,
        )

    # ── Forward to CFN ────────────────────────────────────────────────────────
    try:
        cfn_resp = await create_or_update_shared_memories(
            workspace_id=data.workspace_id,
            mas_id=data.mas_id,
            records=data.records,
            agent_id=data.agent_id,
            request_id=request_id,
        )
    except CfnKnowledgeError as exc:
        _log_ingest_event(
            data=data,
            request_id=request_id,
            est_tokens=est_tokens,
            payload_bytes=payload_bytes,
            latency_ms=(time.perf_counter() - started) * 1000,
            state="error",
            reason=str(exc),
            cfn_status=exc.status_code,
        )
        code = exc.status_code or status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    latency_ms = (time.perf_counter() - started) * 1000
    cfn_message = cfn_resp.get("message")
    cfn_response_id = cfn_resp.get("response_id", request_id)

    if content_hash:
        cache.store(
            content_hash,
            response_id=cfn_response_id,
            message=cfn_message,
            ttl_seconds=ttl,
        )

    _log_ingest_event(
        data=data,
        request_id=request_id,
        est_tokens=est_tokens,
        payload_bytes=payload_bytes,
        latency_ms=latency_ms,
        state="ok",
        cfn_status=status.HTTP_201_CREATED,
        cfn_message=cfn_message,
    )

    _write_audit_event(db, data.mas_id)
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        logger.warning("ingest: audit event failed: %s", exc)

    return KnowledgeIngestResponse(
        cfn_response_id=cfn_response_id,
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
    agg["estimated_cfn_knowledge_input_tokens"] += event.estimated_cfn_knowledge_input_tokens
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
