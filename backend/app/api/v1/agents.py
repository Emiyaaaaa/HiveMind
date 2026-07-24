from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Agent
from app.models.agent import AgentVersion
from app.schemas.agent import (
    AgentCreate,
    AgentRead,
    AgentUpdate,
    AgentVersionDiff,
    AgentVersionRead,
)
from app.services.agent_versions import (
    definition_changed,
    get_agent_version,
    list_agent_versions,
    snapshot_agent,
    version_diff,
)

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
        version=1,
    )
    session.add(agent)
    try:
        await session.flush()
        session.add(snapshot_agent(agent, note="initial"))
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


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    session: AsyncSession = Depends(get_session),
) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    fields_set = payload.model_fields_set
    if "name" in fields_set and payload.name is not None:
        agent.name = payload.name

    new_description = (
        payload.description if "description" in fields_set else agent.description
    )
    new_adapter = payload.adapter if "adapter" in fields_set else agent.adapter
    new_config = (
        dict(payload.config) if "config" in fields_set and payload.config is not None
        else dict(agent.config or {})
    )

    bump = definition_changed(
        agent,
        description=new_description,
        adapter=new_adapter or agent.adapter,
        config=new_config,
        description_set="description" in fields_set,
        adapter_set="adapter" in fields_set,
        config_set="config" in fields_set,
    )

    if "description" in fields_set:
        agent.description = payload.description
    if "adapter" in fields_set and payload.adapter is not None:
        agent.adapter = payload.adapter
    if "config" in fields_set and payload.config is not None:
        agent.config = dict(payload.config)

    if bump:
        agent.version = int(agent.version or 1) + 1
        session.add(snapshot_agent(agent, note=payload.note))

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


@router.get("/{agent_id}/versions", response_model=list[AgentVersionRead])
async def list_versions(
    agent_id: str, session: AsyncSession = Depends(get_session)
) -> list[AgentVersion]:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await list_agent_versions(session, agent_id)


@router.get(
    "/{agent_id}/versions/diff",
    response_model=AgentVersionDiff,
)
async def diff_versions(
    agent_id: str,
    from_version: int = Query(..., alias="from", ge=1),
    to_version: int = Query(..., alias="to", ge=1),
    session: AsyncSession = Depends(get_session),
) -> AgentVersionDiff:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    left = await get_agent_version(session, agent_id, from_version)
    right = await get_agent_version(session, agent_id, to_version)
    if left is None or right is None:
        missing = from_version if left is None else to_version
        raise HTTPException(
            status_code=404, detail=f"Agent version not found: {missing}"
        )
    return AgentVersionDiff.model_validate(version_diff(left, right))


@router.get(
    "/{agent_id}/versions/{version}",
    response_model=AgentVersionRead,
)
async def get_version(
    agent_id: str,
    version: int,
    session: AsyncSession = Depends(get_session),
) -> AgentVersion:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    row = await get_agent_version(session, agent_id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent version not found")
    return row


@router.post(
    "/{agent_id}/versions/{version}/restore",
    response_model=AgentRead,
)
async def restore_version(
    agent_id: str,
    version: int,
    session: AsyncSession = Depends(get_session),
) -> Agent:
    """Restore adapter/config/description from a snapshot as a new version."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    snap = await get_agent_version(session, agent_id, version)
    if snap is None:
        raise HTTPException(status_code=404, detail="Agent version not found")

    if (
        agent.adapter == snap.adapter
        and (agent.config or {}) == (snap.config or {})
        and agent.description == snap.description
    ):
        return agent

    agent.adapter = snap.adapter
    agent.config = dict(snap.config or {})
    agent.description = snap.description
    agent.version = int(agent.version or 1) + 1
    session.add(
        snapshot_agent(agent, note=f"restored from v{version}")
    )
    await session.commit()
    await session.refresh(agent)
    return agent
