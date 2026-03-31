# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Audit event endpoints (internal API).

POST   /api/internal/audit-events
GET    /api/internal/audit-events
GET    /api/internal/audit-events/{event_id}
DELETE /api/internal/audit-events/{event_id}
"""

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import AuditEvent
from app.schemas import VALID_AUDIT_TYPES, VALID_RESOURCE_TYPES, AuditEventCreate, AuditEventRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal/audit-events", tags=["audit"])


@router.post("", status_code=200)
async def create_audit_event(
    body: AuditEventCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new audit event."""
    if body.resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid resource_type: {body.resource_type!r}. Valid: {sorted(VALID_RESOURCE_TYPES)}",
        )
    if body.audit_type not in VALID_AUDIT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid audit_type: {body.audit_type!r}. Valid: {sorted(VALID_AUDIT_TYPES)}",
        )

    now = datetime.now(UTC)
    event = AuditEvent(
        id=uuid4(),
        operation_id=body.operation_id,
        resource_type=body.resource_type,
        resource_identifier=body.resource_identifier,
        audit_type=body.audit_type,
        audit_resource_identifier=body.audit_resource_identifier,
        audit_information=body.audit_information,
        audit_extra_information=body.audit_extra_information,
        created_by=body.created_by,
        created_on=now,
        last_modified_by=body.last_modified_by,
        last_modified_on=now,
    )
    db.add(event)
    await db.commit()
    return {"message": "entry created"}


@router.get("", response_model=list[AuditEventRead])
async def list_audit_events(
    resource_type: str | None = None,
    audit_type: str | None = None,
    db: AsyncSession = Depends(get_async_session),
):
    """List audit events with optional filters."""
    if resource_type and resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid resource_type: {resource_type!r}. Valid: {sorted(VALID_RESOURCE_TYPES)}",
        )
    if audit_type and audit_type not in VALID_AUDIT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid audit_type: {audit_type!r}. Valid: {sorted(VALID_AUDIT_TYPES)}",
        )

    query = select(AuditEvent).order_by(AuditEvent.created_on.desc())
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)
    if audit_type:
        query = query.where(AuditEvent.audit_type == audit_type)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{event_id}", response_model=AuditEventRead)
async def get_audit_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single audit event by UUID."""
    result = await db.execute(select(AuditEvent).where(AuditEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="audit event not found")
    return event


@router.delete("/{event_id}", status_code=204)
async def delete_audit_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    """Delete an audit event by UUID."""
    result = await db.execute(select(AuditEvent).where(AuditEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="audit event not found")
    await db.delete(event)
    await db.commit()
