from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.run import Run, RunStatus
from app.runtime.usage import RunUsage, aggregate_run_usage, usage_from_metadata


class RunCreate(BaseModel):
    agent_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    adapter: str | None = Field(
        default=None,
        description="Override the agent's default adapter for this run.",
    )


class RunRetry(BaseModel):
    checkpoint_index: int | None = Field(
        default=None,
        description="Resume from this checkpoint; latest when omitted.",
    )


class RunResume(BaseModel):
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="Human approval payload merged into the run input.",
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
    cost_usd: float | None = None
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
    usage: RunUsage = Field(default_factory=RunUsage)

    @model_validator(mode="after")
    def fill_usage(self) -> "RunRead":
        if self.steps:
            return self.model_copy(update={"usage": aggregate_run_usage(self.steps)})
        return self


def run_read_from_orm(run: Run) -> RunRead:
    """Build API run DTO with usage from steps or persisted metadata."""
    dto = RunRead.model_validate(run)
    if dto.steps:
        return dto
    stored = usage_from_metadata(run.metadata_)
    if stored is not None:
        return dto.model_copy(update={"usage": stored})
    return dto


EventType = Literal[
    "run.created",
    "run.started",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "run.waiting_human",
    "step.started",
    "step.updated",
    "step.completed",
    "step.failed",
    "token.delta",
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
