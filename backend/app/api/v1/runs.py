from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.events import EventBus, get_event_bus
from app.schemas.run import (
    MessagePage,
    RunCreate,
    RunRead,
    RunResume,
    RunRetry,
    run_read_from_orm,
)
from app.services.run_service import (
    AgentNotFound,
    RunConflict,
    RunNotFound,
    RunService,
)

router = APIRouter(prefix="/runs", tags=["runs"])


def get_run_service(
    session: AsyncSession = Depends(get_session),
    bus: EventBus = Depends(get_event_bus),
) -> RunService:
    return RunService(session=session, bus=bus)


async def _run_read(
    service: RunService,
    run_id: str,
    principal: AuthPrincipal,
) -> RunRead:
    run = await service.get_run(
        run_id,
        with_relations=True,
        tenant_id=principal.tenant_id,
        project_id=principal.project_id,
        agent_id=principal.agent_id,
    )
    truncated = await service.hydrate_run_messages(
        run,
        tenant_id=principal.tenant_id,
        project_id=principal.project_id,
        agent_id=principal.agent_id,
    )
    return run_read_from_orm(run, messages_truncated=truncated)


@router.post("", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: RunCreate,
    service: RunService = Depends(get_run_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> RunRead:
    try:
        run = await service.create_run(
            payload,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {exc}") from exc

    await service.start_run(run.id)
    try:
        return await _run_read(service, run.id, principal)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc


@router.get("", response_model=list[RunRead])
async def list_runs(
    limit: int = 50,
    service: RunService = Depends(get_run_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[RunRead]:
    runs = await service.list_runs(
        limit=limit,
        tenant_id=principal.tenant_id,
        project_id=principal.project_id,
        agent_id=principal.agent_id,
    )
    return [run_read_from_orm(run) for run in runs]


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: str,
    service: RunService = Depends(get_run_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> RunRead:
    try:
        return await _run_read(service, run_id, principal)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc


@router.get("/{run_id}/messages", response_model=MessagePage)
async def list_run_messages(
    run_id: str,
    cursor: int | None = None,
    limit: int = 50,
    service: RunService = Depends(get_run_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> MessagePage:
    try:
        return await service.list_messages(
            run_id,
            cursor=cursor,
            limit=limit,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc


@router.post("/{run_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_run(
    run_id: str,
    service: RunService = Depends(get_run_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> None:
    try:
        await service.cancel_run(
            run_id, tenant_id=principal.tenant_id,
            project_id=principal.project_id, agent_id=principal.agent_id,
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc


@router.post("/{run_id}/retry", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_run(
    run_id: str,
    payload: RunRetry | None = None,
    service: RunService = Depends(get_run_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> RunRead:
    try:
        await service.retry_run(
            run_id, payload, tenant_id=principal.tenant_id,
            project_id=principal.project_id, agent_id=principal.agent_id,
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _run_read(service, run_id, principal)


@router.post("/{run_id}/resume", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def resume_run(
    run_id: str,
    payload: RunResume | None = None,
    service: RunService = Depends(get_run_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> RunRead:
    try:
        await service.resume_run(
            run_id, payload, tenant_id=principal.tenant_id,
            project_id=principal.project_id, agent_id=principal.agent_id,
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await _run_read(service, run_id, principal)
