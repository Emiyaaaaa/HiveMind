from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.schemas.run import RunRead, run_read_from_orm
from app.schemas.thread import (
    ThreadCreate,
    ThreadMessagePage,
    ThreadRead,
)
from app.services.thread_service import (
    AgentNotFound,
    ThreadNotFound,
    ThreadService,
)

router = APIRouter(prefix="/threads", tags=["threads"])


def get_thread_service(
    session: AsyncSession = Depends(get_session),
) -> ThreadService:
    return ThreadService(session=session)


@router.post("", response_model=ThreadRead, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: ThreadCreate,
    service: ThreadService = Depends(get_thread_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> ThreadRead:
    try:
        thread = await service.create_thread(
            payload,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except AgentNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {exc}") from exc
    return ThreadRead.model_validate(thread)


@router.get("", response_model=list[ThreadRead])
async def list_threads(
    limit: int = 50,
    service: ThreadService = Depends(get_thread_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[ThreadRead]:
    threads = await service.list_threads(
        tenant_id=principal.tenant_id,
        project_id=principal.project_id,
        agent_id=principal.agent_id,
        limit=limit,
    )
    return [ThreadRead.model_validate(t) for t in threads]


@router.get("/{thread_id}", response_model=ThreadRead)
async def get_thread(
    thread_id: str,
    service: ThreadService = Depends(get_thread_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> ThreadRead:
    try:
        thread = await service.get_thread(
            thread_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except ThreadNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Thread not found: {exc}") from exc
    return ThreadRead.model_validate(thread)


@router.get("/{thread_id}/messages", response_model=ThreadMessagePage)
async def list_thread_messages(
    thread_id: str,
    cursor: str | None = None,
    limit: int = 50,
    service: ThreadService = Depends(get_thread_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> ThreadMessagePage:
    try:
        return await service.list_thread_messages(
            thread_id,
            cursor=cursor,
            limit=limit,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except ThreadNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Thread not found: {exc}") from exc


@router.get("/{thread_id}/runs", response_model=list[RunRead])
async def list_thread_runs(
    thread_id: str,
    limit: int = 50,
    service: ThreadService = Depends(get_thread_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[RunRead]:
    try:
        runs = await service.list_thread_runs(
            thread_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
            limit=limit,
        )
    except ThreadNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Thread not found: {exc}") from exc
    return [run_read_from_orm(run) for run in runs]
