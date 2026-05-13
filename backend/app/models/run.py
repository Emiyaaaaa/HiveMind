"""Runtime entities: Run, Step, Message, ToolCall, Checkpoint.

These tables form the core observability surface of AgentFlow. Every adapter
writes into the same shape so the UI and SDK can render any agent execution
without knowing the underlying framework.
"""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.base import Base


def _ulid() -> str:
    return str(ULID())


class RunStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_HUMAN = "waiting_human"


class Run(Base):
    """A single invocation of an agent.

    A run is the top-level unit users observe and operate on (cancel, retry,
    resume). It owns an ordered stream of `Step` rows, which in turn own
    `Message` and `ToolCall` rows.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    adapter: Mapped[str] = mapped_column(String(64))
    status: Mapped[RunStatus] = mapped_column(
        String(32), default=RunStatus.PENDING, index=True
    )

    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    agent: Mapped[Agent] = relationship(back_populates="runs")  # noqa: F821
    steps: Mapped[list[Step]] = relationship(
        back_populates="run",
        order_by="Step.index",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list[Message]] = relationship(
        back_populates="run",
        order_by="Message.index",
        cascade="all, delete-orphan",
    )
    checkpoints: Mapped[list[Checkpoint]] = relationship(
        back_populates="run",
        order_by="Checkpoint.index",
        cascade="all, delete-orphan",
    )


class Step(Base):
    """A single executor tick inside a run.

    For LangGraph this maps to a graph node invocation; for AutoGen it can map
    to an agent turn. The `node` field is free-form text so any adapter can
    write a sensible label.
    """

    __tablename__ = "steps"
    __table_args__ = (Index("ix_steps_run_index", "run_id", "index"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    index: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(128))
    status: Mapped[RunStatus] = mapped_column(String(32), default=RunStatus.RUNNING)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)

    run: Mapped[Run] = relationship(back_populates="steps")
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
    )


class Message(Base):
    """A message exchanged during the run.

    Messages are scoped to a run, not a step, because the same logical
    conversation may span multiple executor ticks. Use `step_id` when an
    adapter wants to associate a message with a specific node.
    """

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_run_index", "run_id", "index"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str | None] = mapped_column(
        ForeignKey("steps.id", ondelete="SET NULL"), nullable=True
    )
    index: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))  # system|user|assistant|tool
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="messages")


class ToolCall(Base):
    """A tool invocation issued from a step."""

    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_tool_calls_step", "step_id"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    step_id: Mapped[str] = mapped_column(
        ForeignKey("steps.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    step: Mapped[Step] = relationship(back_populates="tool_calls")


class Checkpoint(Base):
    """Adapter-defined snapshot used for resume / replay.

    The `state` blob is opaque to AgentFlow: each adapter encodes what it
    needs (LangGraph snapshot bytes encoded as JSON-safe payload, AutoGen
    conversation history, etc.). The runtime only guarantees ordering and
    durability.
    """

    __tablename__ = "checkpoints"
    __table_args__ = (Index("ix_checkpoints_run_index", "run_id", "index"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    index: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="checkpoints")
