from typing import Any

from sqlalchemy import JSON, String
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
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    adapter: Mapped[str] = mapped_column(String(64), default="echo")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    runs: Mapped[list["Run"]] = relationship(  # noqa: F821 -- forward ref
        back_populates="agent",
        cascade="all, delete-orphan",
    )
