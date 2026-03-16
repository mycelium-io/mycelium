"""Workspace CRUD — POST/GET/DELETE /api/workspaces."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import Workspace
from app.schemas import WorkspaceCreate, WorkspaceRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceRead, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    db: AsyncSession = Depends(get_async_session),
):
    workspace = Workspace(name=body.name)
    db.add(workspace)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="workspace name already exists")
    await db.refresh(workspace)
    return workspace


@router.get("", response_model=list[WorkspaceRead])
async def list_workspaces(db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(Workspace).order_by(Workspace.created_at))
    return result.scalars().all()


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(workspace_id: UUID, db: AsyncSession = Depends(get_async_session)):
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: UUID, db: AsyncSession = Depends(get_async_session)):
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    await db.delete(workspace)
    await db.commit()
