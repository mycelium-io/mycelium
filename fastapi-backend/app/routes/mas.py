# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""MAS CRUD — POST/GET/DELETE /api/workspaces/{workspace_id}/mas."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import MAS, Workspace
from app.schemas import MASCreate, MASRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces/{workspace_id}/mas", tags=["mas"])


async def _get_workspace_or_404(workspace_id: UUID, db: AsyncSession) -> Workspace:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace


@router.post("", response_model=MASRead, status_code=201)
async def create_mas(
    workspace_id: UUID,
    body: MASCreate,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_workspace_or_404(workspace_id, db)
    mas = MAS(workspace_id=workspace_id, name=body.name, config=body.config)
    db.add(mas)
    await db.commit()
    await db.refresh(mas)
    return mas


@router.get("", response_model=list[MASRead])
async def list_mas(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_workspace_or_404(workspace_id, db)
    result = await db.execute(
        select(MAS).where(MAS.workspace_id == workspace_id).order_by(MAS.created_at)
    )
    return result.scalars().all()


@router.get("/{mas_id}", response_model=MASRead)
async def get_mas(
    workspace_id: UUID,
    mas_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_workspace_or_404(workspace_id, db)
    mas = await db.get(MAS, mas_id)
    if mas is None or mas.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="MAS not found")
    return mas


@router.delete("/{mas_id}", status_code=204)
async def delete_mas(
    workspace_id: UUID,
    mas_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_workspace_or_404(workspace_id, db)
    mas = await db.get(MAS, mas_id)
    if mas is None or mas.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="MAS not found")
    await db.delete(mas)
    await db.commit()
