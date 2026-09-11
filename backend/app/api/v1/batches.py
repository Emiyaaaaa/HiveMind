from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.events import EventBus, get_event_bus
from app.schemas.batch import BatchCreate, BatchRead
from app.schemas.run import RunRead, run_header_from_orm
from app.services.batch_service import (
    BatchNotFound,
    BatchService,
    BatchValidationError,
)
from app.services.run_service import AgentNotFound


router = APIRouter(prefix="/batches", tags=["batches"])


def get_batch_service(
    session: AsyncSession = Depends(get_session),
    bus: EventBus = Depends(get_event_bus),
) -> BatchService:
    return BatchService(session=session, bus=bus)


@router.post("", response_model=BatchRead, status_code=status.HTTP_202_ACCEPTED)
async def create_batch(
    payload: BatchCreate,
    service: BatchService = Depends(get_batch_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> BatchRead:
    try:
        return await service.create_batch(
            payload,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {exc}") from exc
    except BatchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[BatchRead])
async def list_batches(
    limit: int = 50,
    service: BatchService = Depends(get_batch_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[BatchRead]:
    return await service.list_batches(
        tenant_id=principal.tenant_id,
        project_id=principal.project_id,
        agent_id=principal.agent_id,
        limit=limit,
    )


@router.get("/{batch_id}", response_model=BatchRead)
async def get_batch(
    batch_id: str,
    service: BatchService = Depends(get_batch_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> BatchRead:
    try:
        return await service.get_batch(
            batch_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except BatchNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Batch not found: {exc}") from exc


@router.get("/{batch_id}/runs", response_model=list[RunRead])
async def list_batch_runs(
    batch_id: str,
    service: BatchService = Depends(get_batch_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[RunRead]:
    try:
        runs = await service.list_batch_runs(
            batch_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except BatchNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Batch not found: {exc}") from exc
    return [run_header_from_orm(run) for run in runs]
