from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.run import RunStatus


class RunCreate(BaseModel):
    agent_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    adapter: str | None = Field(
        default=None,
        description="Override the agent's default adapter for this run.",
    )


class ToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    latency_ms: int | None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    index: int
    role: str
    name: str | None
    content: str
    tool_call_id: str | None
    extra: dict[str, Any]
    created_at: datetime


class StepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    index: int
    node: str
    status: RunStatus
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    latency_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    tool_calls: list[ToolCallRead] = []
    created_at: datetime
    updated_at: datetime


class CheckpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    index: int
    label: str | None
    created_at: datetime


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    adapter: str
    status: RunStatus
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[StepRead] = []
    messages: list[MessageRead] = []
    checkpoints: list[CheckpointRead] = []


EventType = Literal[
    "run.created",
    "run.started",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "step.started",
    "step.completed",
    "step.failed",
    "message.created",
    "tool_call.started",
    "tool_call.completed",
    "checkpoint.created",
    "log",
]


class RunEvent(BaseModel):
    """Server-Sent Event payload broadcast on every run state change."""

    type: EventType
    run_id: str
    at: datetime
    data: dict[str, Any] = Field(default_factory=dict)
