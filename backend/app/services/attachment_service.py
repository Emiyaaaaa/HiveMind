"""Upload, bind, and erase multimodal attachments."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.attachment import Attachment
from app.runtime.object_store import (
    ObjectStore,
    attachment_storage_key,
    get_object_store,
    sha256_hex,
)
from app.schemas.attachment import AttachmentRead, attachment_ref, attachment_url


class AttachmentNotFound(Exception):
    def __init__(self, attachment_id: str) -> None:
        self.attachment_id = attachment_id
        super().__init__(attachment_id)


class AttachmentTooLarge(Exception):
    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(f"attachment {size} bytes exceeds limit {limit}")


class AttachmentService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        store: ObjectStore | None = None,
    ) -> None:
        self.session = session
        self.store = store or get_object_store()

    async def create(
        self,
        *,
        tenant_id: str,
        filename: str,
        media_type: str,
        data: bytes,
        caption: str | None = None,
    ) -> Attachment:
        settings = get_settings()
        if len(data) > settings.attachment_max_bytes:
            raise AttachmentTooLarge(len(data), settings.attachment_max_bytes)
        if not data:
            raise ValueError("empty attachment")

        attachment = Attachment(
            tenant_id=tenant_id,
            media_type=media_type or "application/octet-stream",
            filename=filename or "blob",
            storage_key="",  # filled after id is known
            size_bytes=len(data),
            sha256=sha256_hex(data),
            caption=caption,
        )
        self.session.add(attachment)
        await self.session.flush()

        key = attachment_storage_key(
            tenant_id=tenant_id,
            attachment_id=attachment.id,
            filename=attachment.filename,
        )
        await self.store.put(key, data, media_type=attachment.media_type)
        attachment.storage_key = key
        await self.session.commit()
        await self.session.refresh(attachment)
        return attachment

    async def get(
        self,
        attachment_id: str,
        *,
        tenant_id: str | None = None,
    ) -> Attachment:
        attachment = await self.session.get(Attachment, attachment_id)
        if attachment is None:
            raise AttachmentNotFound(attachment_id)
        if tenant_id is not None and attachment.tenant_id != tenant_id:
            raise AttachmentNotFound(attachment_id)
        return attachment

    async def get_bytes(
        self,
        attachment_id: str,
        *,
        tenant_id: str | None = None,
    ) -> tuple[Attachment, bytes]:
        attachment = await self.get(attachment_id, tenant_id=tenant_id)
        data = await self.store.get(attachment.storage_key)
        return attachment, data

    async def list_for_run(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[Attachment]:
        stmt = select(Attachment).where(Attachment.run_id == run_id)
        if tenant_id is not None:
            stmt = stmt.where(Attachment.tenant_id == tenant_id)
        stmt = stmt.order_by(Attachment.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bind_to_run(
        self,
        *,
        run_id: str,
        tenant_id: str,
        attachment_ids: list[str],
    ) -> list[Attachment]:
        """Associate previously uploaded attachments with a run."""
        if not attachment_ids:
            return []
        bound: list[Attachment] = []
        for attachment_id in attachment_ids:
            attachment = await self.get(attachment_id, tenant_id=tenant_id)
            if attachment.run_id and attachment.run_id != run_id:
                raise AttachmentNotFound(attachment_id)
            attachment.run_id = run_id
            bound.append(attachment)
        await self.session.commit()
        return bound

    async def bind_message(
        self,
        *,
        attachment_ids: list[str],
        message_id: str,
        tenant_id: str,
    ) -> None:
        if not attachment_ids:
            return
        for attachment_id in attachment_ids:
            attachment = await self.get(attachment_id, tenant_id=tenant_id)
            attachment.message_id = message_id
        await self.session.commit()

    async def resolve_input_attachments(
        self,
        run_input: dict[str, Any],
        *,
        tenant_id: str,
        run_id: str | None = None,
    ) -> list[Attachment]:
        """Load attachments referenced by ``input.attachments`` (id list or refs)."""
        raw = run_input.get("attachments")
        if not isinstance(raw, list) or not raw:
            return []
        ids: list[str] = []
        for item in raw:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.append(item["id"])
        if not ids:
            return []
        if run_id:
            return await self.bind_to_run(
                run_id=run_id, tenant_id=tenant_id, attachment_ids=ids
            )
        out: list[Attachment] = []
        for attachment_id in ids:
            out.append(await self.get(attachment_id, tenant_id=tenant_id))
        return out

    async def erase_run(self, run_id: str, *, tenant_id: str | None = None) -> int:
        """Delete attachment rows + blobs for a run. Does not commit."""
        stmt = select(Attachment).where(Attachment.run_id == run_id)
        if tenant_id is not None:
            stmt = stmt.where(Attachment.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        for row in rows:
            try:
                await self.store.delete(row.storage_key)
            except Exception:
                pass
        if rows:
            await self.session.execute(
                delete(Attachment).where(Attachment.id.in_([r.id for r in rows]))
            )
        return len(rows)

    async def erase_tenant(self, tenant_id: str) -> int:
        """Delete all attachments for a tenant. Does not commit."""
        stmt = select(Attachment).where(Attachment.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        for row in rows:
            try:
                await self.store.delete(row.storage_key)
            except Exception:
                pass
        if rows:
            await self.session.execute(
                delete(Attachment).where(Attachment.tenant_id == tenant_id)
            )
        return len(rows)

    def to_read(self, attachment: Attachment) -> AttachmentRead:
        return AttachmentRead(
            id=attachment.id,
            tenant_id=attachment.tenant_id,
            run_id=attachment.run_id,
            message_id=attachment.message_id,
            media_type=attachment.media_type,
            filename=attachment.filename,
            size_bytes=attachment.size_bytes,
            sha256=attachment.sha256,
            caption=attachment.caption,
            url=attachment_url(attachment.id),
            created_at=attachment.created_at,
            updated_at=attachment.updated_at,
        )


class AttachmentErasureHook:
    """Retention hook: drop attachment rows + object-store blobs with L0 erase."""

    async def erase_run(self, session: AsyncSession, run: Any) -> dict[str, int]:
        service = AttachmentService(session)
        deleted = await service.erase_run(
            run.id, tenant_id=getattr(run, "tenant_id", None)
        )
        return {"attachments_deleted": deleted}

    async def erase_tenant(self, session: AsyncSession, tenant_id: str) -> dict[str, int]:
        service = AttachmentService(session)
        deleted = await service.erase_tenant(tenant_id)
        return {"attachments_deleted": deleted}


def refs_from_attachments(attachments: list[Attachment]) -> list[dict[str, Any]]:
    return [attachment_ref(a) for a in attachments]
