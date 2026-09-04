from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthPrincipal, Role, require_role
from app.db.session import get_session
from app.schemas.attachment import AttachmentRead
from app.services.attachment_service import (
    AttachmentNotFound,
    AttachmentService,
    AttachmentTooLarge,
)

router = APIRouter(prefix="/attachments", tags=["attachments"])


def get_attachment_service(
    session: AsyncSession = Depends(get_session),
) -> AttachmentService:
    return AttachmentService(session=session)


@router.post("", response_model=AttachmentRead, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    service: AttachmentService = Depends(get_attachment_service),
    principal: AuthPrincipal = Depends(require_role(Role.OPERATOR)),
) -> AttachmentRead:
    data = await file.read()
    try:
        attachment = await service.create(
            tenant_id=principal.tenant_id,
            filename=file.filename or "blob",
            media_type=file.content_type or "application/octet-stream",
            data=data,
            caption=caption,
        )
    except AttachmentTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail=f"Attachment too large: {exc.size} > {exc.limit} bytes",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service.to_read(attachment)


@router.get("/{attachment_id}", response_model=AttachmentRead)
async def get_attachment_meta(
    attachment_id: str,
    service: AttachmentService = Depends(get_attachment_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> AttachmentRead:
    try:
        attachment = await service.get(attachment_id, tenant_id=principal.tenant_id)
    except AttachmentNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Attachment not found: {exc}"
        ) from exc
    return service.to_read(attachment)


@router.get("/{attachment_id}/content")
async def download_attachment(
    attachment_id: str,
    service: AttachmentService = Depends(get_attachment_service),
    principal: AuthPrincipal = Depends(require_role(Role.VIEWER)),
) -> Response:
    try:
        attachment, data = await service.get_bytes(
            attachment_id, tenant_id=principal.tenant_id
        )
    except AttachmentNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Attachment not found: {exc}"
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"Attachment blob missing: {attachment_id}"
        ) from exc
    headers = {
        "Content-Disposition": f'inline; filename="{attachment.filename}"',
    }
    return Response(
        content=data,
        media_type=attachment.media_type,
        headers=headers,
    )
