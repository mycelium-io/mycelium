"""Agent CRUD — POST/GET/PATCH/DELETE /api/workspaces/{wid}/mas/{mid}/agents."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import MAS, Agent, Workspace
from app.schemas import AgentCreate, AgentRead, AgentUpdate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/mas/{mas_id}/agents",
    tags=["agents"],
)


async def _get_mas_or_404(workspace_id: UUID, mas_id: UUID, db: AsyncSession) -> MAS:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    mas = await db.get(MAS, mas_id)
    if mas is None or mas.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="MAS not found")
    return mas


@router.post("", response_model=AgentRead, status_code=201)
async def create_agent(
    workspace_id: UUID,
    mas_id: UUID,
    body: AgentCreate,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_mas_or_404(workspace_id, mas_id, db)
    agent = Agent(
        mas_id=mas_id,
        name=body.name,
        memory_provider_url=body.memory_provider_url,
        memory_config=body.memory_config,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("", response_model=list[AgentRead])
async def list_agents(
    workspace_id: UUID,
    mas_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_mas_or_404(workspace_id, mas_id, db)
    result = await db.execute(
        select(Agent).where(Agent.mas_id == mas_id).order_by(Agent.created_at)
    )
    return result.scalars().all()


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_mas_or_404(workspace_id, mas_id, db)
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.mas_id != mas_id:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_mas_or_404(workspace_id, mas_id, db)
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.mas_id != mas_id:
        raise HTTPException(status_code=404, detail="agent not found")
    if body.name is not None:
        agent.name = body.name
    if body.memory_provider_url is not None:
        agent.memory_provider_url = body.memory_provider_url
    if body.memory_config is not None:
        agent.memory_config = body.memory_config
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    workspace_id: UUID,
    mas_id: UUID,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_session),
):
    await _get_mas_or_404(workspace_id, mas_id, db)
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.mas_id != mas_id:
        raise HTTPException(status_code=404, detail="agent not found")
    await db.delete(agent)
    await db.commit()
