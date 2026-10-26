from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class Project(Base):
    """A project belongs to one organization (the existing ``tenant_id``)."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_projects_tenant_name"),
        Index("ix_projects_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    agents: Mapped[list["Agent"]] = relationship(back_populates="project")  # noqa: F821
