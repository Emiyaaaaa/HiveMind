"""Multimodal attachment metadata (blobs live in object storage)."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class Attachment(Base):
    """A file attached to a run / message.

    ``Message.content`` stays plain text; attachment refs live in
    ``Message.extra.attachments`` and this table. Binary bytes are stored
    under ``storage_key`` in the configured object store (local FS by default;
    the same store is reserved for future memory-layer document chunks).
    """

    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_tenant_id", "tenant_id"),
        Index("ix_attachments_run_id", "run_id"),
        Index("ix_attachments_message_id", "message_id"),
        Index("ix_attachments_storage_key", "storage_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["Run | None"] = relationship()  # noqa: F821
    message: Mapped["Message | None"] = relationship()  # noqa: F821
