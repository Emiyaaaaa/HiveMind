from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.events import EventBus, get_event_bus
from app.schemas.retention import (
    EraseRunDataResponse,
    EraseTenantDataResponse,
    RetentionPurgeRequest,
    RetentionPurgeResponse,
)
from app.services.retention_service import RetentionService, RunConflictForErase
from app.services.run_service import RunNotFound

router = APIRouter(tags=["retention"])


def get_retention_service(
    session: AsyncSession = Depends(get_session),
    bus: EventBus = Depends(get_event_bus),
) -> RetentionService:
    return RetentionService(session=session, bus=bus)


@router.post(
    "/runs/{run_id}/erase",
    response_model=EraseRunDataResponse,
    status_code=status.HTTP_200_OK,
)
async def erase_run_data(
    run_id: str,
    service: RetentionService = Depends(get_retention_service),
    principal: AuthPrincipal = Depends(require_role(Role.ADMIN)),
) -> EraseRunDataResponse:
    """GDPR-style erasure of run transcript data (messages + checkpoints)."""
    try:
        result = await service.erase_run_data(
            run_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc
    except RunConflictForErase as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return EraseRunDataResponse(
        run_id=run_id,
        messages_deleted=result["messages_deleted"],
        checkpoints_deleted=result["checkpoints_deleted"],
    )


@router.post(
    "/organization/erase",
    response_model=EraseTenantDataResponse,
    status_code=status.HTTP_200_OK,
)
async def erase_tenant_data(
    service: RetentionService = Depends(get_retention_service),
    principal: AuthPrincipal = Depends(require_role(Role.ADMIN)),
) -> EraseTenantDataResponse:
    """Erase all messages and checkpoints for the authenticated tenant."""
    result = await service.erase_tenant_data(principal.tenant_id)
    return EraseTenantDataResponse(
        tenant_id=principal.tenant_id,
        runs_processed=result["runs_processed"],
        messages_deleted=result["messages_deleted"],
        checkpoints_deleted=result["checkpoints_deleted"],
    )


@router.post(
    "/retention/purge",
    response_model=RetentionPurgeResponse,
    status_code=status.HTTP_200_OK,
)
async def purge_expired_retention(
    payload: RetentionPurgeRequest | None = None,
    service: RetentionService = Depends(get_retention_service),
    principal: AuthPrincipal = Depends(require_role(Role.ADMIN)),
) -> RetentionPurgeResponse:
    """Purge terminal runs older than the configured tenant TTL."""
    req = payload or RetentionPurgeRequest()
    if req.tenant_id is not None and req.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Resource not found")

    result = await service.purge_expired(
        tenant_id=req.tenant_id or principal.tenant_id,
        dry_run=req.dry_run,
    )
    return RetentionPurgeResponse(
        tenant_id=req.tenant_id or principal.tenant_id,
        runs_purged=result["runs_purged"],
        messages_deleted=result["messages_deleted"],
        checkpoints_deleted=result["checkpoints_deleted"],
    )
