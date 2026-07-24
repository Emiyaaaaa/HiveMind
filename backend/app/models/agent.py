from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.base import Base


def _ulid() -> str:
    return str(ULID())


class Agent(Base):
    """An agent definition that can be invoked through a Run.

    An agent is intentionally lightweight: a name, a role description, the
    adapter that knows how to run it, and an opaque config blob. The adapter
    decides how to interpret `config` (graph definition, role prompts, tool
    list, etc.).

    ``version`` is a monotonic integer that bumps whenever adapter / config /
    description change; each bump is also stored in ``agent_versions``.
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    adapter: Mapped[str] = mapped_column(String(64), default="echo")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    runs: Mapped[list["Run"]] = relationship(  # noqa: F821 -- forward ref
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="agent",
        order_by="AgentVersion.version",
        cascade="all, delete-orphan",
    )


class AgentVersion(Base):
    """Immutable snapshot of an agent definition at a given version number."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        Index("ix_agent_versions_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="versions")
