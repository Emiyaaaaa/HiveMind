from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.events import EventBus, get_event_bus
from app.schemas.run import RunCreate, RunRead, RunResume, RunRetry, run_read_from_orm
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


@router.post("", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: RunCreate, service: RunService = Depends(get_run_service)
) -> RunRead:
    try:
        run = await service.create_run(payload)
    except AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {exc}") from exc

    await service.start_run(run.id)
    run = await service.get_run(run.id, with_relations=True)
    return run_read_from_orm(run)


@router.get("", response_model=list[RunRead])
async def list_runs(
    limit: int = 50, service: RunService = Depends(get_run_service)
) -> list[RunRead]:
    runs = await service.list_runs(limit=limit)
    return [run_read_from_orm(run) for run in runs]


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: str, service: RunService = Depends(get_run_service)
) -> RunRead:
    try:
        run = await service.get_run(run_id, with_relations=True)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc
    return run_read_from_orm(run)


@router.post("/{run_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_run(
    run_id: str, service: RunService = Depends(get_run_service)
) -> None:
    try:
        await service.cancel_run(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc


@router.post("/{run_id}/retry", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_run(
    run_id: str,
    payload: RunRetry | None = None,
    service: RunService = Depends(get_run_service),
) -> RunRead:
    try:
        run = await service.retry_run(run_id, payload)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run_read_from_orm(run)


@router.post("/{run_id}/resume", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def resume_run(
    run_id: str,
    payload: RunResume | None = None,
    service: RunService = Depends(get_run_service),
) -> RunRead:
    try:
        run = await service.resume_run(run_id, payload)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run_read_from_orm(run)
