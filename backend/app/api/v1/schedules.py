from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.runs import _run_read, get_run_service
from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.events import EventBus, get_event_bus
from app.schemas.run import RunRead, run_header_from_orm
from app.schemas.schedule import (
    ScheduleCreate,
    ScheduleRead,
    ScheduleTrigger,
    ScheduleUpdate,
)
from app.services.run_service import AgentNotFound, RunService
from app.services.schedule_service import (
    ScheduleNotFound,
    ScheduleService,
    ScheduleValidationError,
    schedule_to_read,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


def get_schedule_service(
    session: AsyncSession = Depends(get_session),
    bus: EventBus = Depends(get_event_bus),
) -> ScheduleService:
    return ScheduleService(session=session, bus=bus)


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    service: ScheduleService = Depends(get_schedule_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> ScheduleRead:
    try:
        row = await service.create_schedule(
            payload,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {exc}") from exc
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schedule_to_read(row)


@router.get("", response_model=list[ScheduleRead])
async def list_schedules(
    limit: int = 50,
    service: ScheduleService = Depends(get_schedule_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[ScheduleRead]:
    rows = await service.list_schedules(
        tenant_id=principal.tenant_id,
        project_id=principal.project_id,
        agent_id=principal.agent_id,
        limit=limit,
    )
    return [schedule_to_read(row) for row in rows]


@router.get("/{schedule_id}", response_model=ScheduleRead)
async def get_schedule(
    schedule_id: str,
    service: ScheduleService = Depends(get_schedule_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> ScheduleRead:
    try:
        row = await service.get_schedule(
            schedule_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except ScheduleNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Schedule not found: {exc}"
        ) from exc
    return schedule_to_read(row)


@router.patch("/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdate,
    service: ScheduleService = Depends(get_schedule_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> ScheduleRead:
    try:
        row = await service.update_schedule(
            schedule_id,
            payload,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except ScheduleNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Schedule not found: {exc}"
        ) from exc
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schedule_to_read(row)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: str,
    service: ScheduleService = Depends(get_schedule_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> None:
    try:
        await service.delete_schedule(
            schedule_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except ScheduleNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Schedule not found: {exc}"
        ) from exc


@router.post(
    "/{schedule_id}/trigger",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_schedule(
    schedule_id: str,
    payload: ScheduleTrigger | None = None,
    service: ScheduleService = Depends(get_schedule_service),
    run_service: RunService = Depends(get_run_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> RunRead:
    body = payload or ScheduleTrigger()
    try:
        run = await service.trigger_schedule(
            schedule_id,
            advance=body.advance,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except ScheduleNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Schedule not found: {exc}"
        ) from exc
    except AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {exc}") from exc
    return await _run_read(run_service, run.id, principal)


@router.get("/{schedule_id}/runs", response_model=list[RunRead])
async def list_schedule_runs(
    schedule_id: str,
    limit: int = 50,
    service: ScheduleService = Depends(get_schedule_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[RunRead]:
    try:
        runs = await service.list_schedule_runs(
            schedule_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
            limit=limit,
        )
    except ScheduleNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Schedule not found: {exc}"
        ) from exc
    return [run_header_from_orm(run) for run in runs]
