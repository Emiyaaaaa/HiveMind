from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.schemas.quota import QuotaConfigWrite, QuotaStatus
from app.services.quota_service import QuotaService

router = APIRouter(prefix="/tenant", tags=["tenant"])


@router.get("/quota", response_model=QuotaStatus)
async def get_tenant_quota(
    session: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> QuotaStatus:
    return QuotaStatus.model_validate(
        await QuotaService(session).status_for_tenant(principal.tenant_id)
    )


@router.put("/quota", response_model=QuotaStatus)
async def put_tenant_quota(
    payload: QuotaConfigWrite,
    session: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_role(Role.ADMIN)),
) -> QuotaStatus:
    principal.require_organization(principal.tenant_id, Role.ADMIN)
    service = QuotaService(session)
    await service.upsert_tenant_config(principal.tenant_id, payload.model_dump())
    body = await service.status_for_tenant(principal.tenant_id)
    await session.commit()
    return QuotaStatus.model_validate(body)
