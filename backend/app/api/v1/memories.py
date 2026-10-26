"""List, write, and forget memory items. Episodes are written by the worker."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.schemas.memory import MemoryCreate, MemoryRead, memory_read
from app.services.episode_service import EpisodeService, MemoryNotFound, MemoryRejected

router = APIRouter(prefix="/memories", tags=["memories"])


def get_episode_service(session: AsyncSession = Depends(get_session)) -> EpisodeService:
    return EpisodeService(session)


@router.get("", response_model=list[MemoryRead])
async def search_memories(
    q: str = "",
    scope: str | None = None,
    kind: str | None = None,
    thread_id: str | None = None,
    agent_id: str | None = None,
    limit: int = 20,
    service: EpisodeService = Depends(get_episode_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[MemoryRead]:
    rows = await service.search(
        tenant_id=principal.tenant_id,
        query=q,
        scope=scope,
        kind=kind,
        thread_id=thread_id,
        agent_id=principal.agent_id or agent_id,
        project_id=principal.project_id,
        limit=limit,
    )
    return [memory_read(item, score) for item, score in rows]


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate,
    service: EpisodeService = Depends(get_episode_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> MemoryRead:
    if principal.agent_id and payload.agent_id and payload.agent_id != principal.agent_id:
        raise HTTPException(status_code=404, detail="Memory not found")
    try:
        item = await service.store(
            tenant_id=principal.tenant_id,
            content=payload.content,
            kind=payload.kind,
            scope=payload.scope,
            agent_id=principal.agent_id or payload.agent_id,
            thread_id=payload.thread_id,
            project_id=principal.project_id or payload.project_id,
            user_id=payload.user_id,
            expires_at=payload.expires_at,
            metadata=payload.metadata,
        )
    except MemoryRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return memory_read(item)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    service: EpisodeService = Depends(get_episode_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> None:
    try:
        await service.delete(
            memory_id,
            tenant_id=principal.tenant_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
        )
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Memory not found: {exc}") from exc
