from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.models import Project
from app.schemas.project import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_role(Role.ADMIN)),
) -> Project:
    principal.require_organization(principal.tenant_id, Role.ADMIN)
    project = Project(
        tenant_id=principal.tenant_id, name=payload.name, description=payload.description
    )
    session.add(project)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Project name already exists") from exc
    await session.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    session: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> list[Project]:
    if principal.agent_id is not None:
        return []
    stmt = select(Project).where(Project.tenant_id == principal.tenant_id)
    if principal.project_id is not None:
        stmt = stmt.where(Project.id == principal.project_id)
    result = await session.execute(stmt.order_by(Project.created_at.desc()))
    return list(result.scalars())


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    principal.require_project(project.tenant_id, project.id, Role.VIEWER)
    return project
