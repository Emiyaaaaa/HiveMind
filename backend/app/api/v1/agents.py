from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Agent
from app.schemas.agent import AgentCreate, AgentRead

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate, session: AsyncSession = Depends(get_session)
) -> Agent:
    agent = Agent(
        name=payload.name,
        description=payload.description,
        adapter=payload.adapter,
        config=payload.config,
    )
    session.add(agent)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent name already exists: {payload.name}",
        ) from exc
    await session.refresh(agent)
    return agent


@router.get("", response_model=list[AgentRead])
async def list_agents(session: AsyncSession = Depends(get_session)) -> list[Agent]:
    result = await session.execute(select(Agent).order_by(Agent.created_at.desc()))
    return list(result.scalars())


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: str, session: AsyncSession = Depends(get_session)
) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent
