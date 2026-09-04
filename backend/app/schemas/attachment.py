"""Attachment API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    run_id: str | None = None
    message_id: str | None = None
    media_type: str
    filename: str
    size_bytes: int
    sha256: str
    caption: str | None = None
    url: str = Field(description="Relative download path under the API root.")
    created_at: datetime
    updated_at: datetime


def attachment_url(attachment_id: str) -> str:
    return f"/v1/attachments/{attachment_id}"


def attachment_ref(attachment: object) -> dict[str, object]:
    """Compact ref stored on ``Message.extra.attachments`` / SSE payloads."""
    return {
        "id": getattr(attachment, "id"),
        "media_type": getattr(attachment, "media_type"),
        "filename": getattr(attachment, "filename"),
        "size_bytes": int(getattr(attachment, "size_bytes") or 0),
        "url": attachment_url(str(getattr(attachment, "id"))),
        "caption": getattr(attachment, "caption", None),
        "sha256": getattr(attachment, "sha256", None),
    }
