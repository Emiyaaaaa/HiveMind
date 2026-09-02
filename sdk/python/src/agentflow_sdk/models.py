"""Data models aligned with openapi/openapi.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class RunUsage:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int | None = None
    step_count: int = 0
    failed_step_count: int = 0
    tool_call_count: int = 0
    failed_tool_call_count: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> RunUsage:
        if not data:
            return cls()
        return cls(
            tokens_in=int(data.get("tokens_in", 0)),
            tokens_out=int(data.get("tokens_out", 0)),
            cost_usd=float(data.get("cost_usd", 0.0)),
            latency_ms=data.get("latency_ms"),
            step_count=int(data.get("step_count", 0)),
            failed_step_count=int(data.get("failed_step_count", 0)),
            tool_call_count=int(data.get("tool_call_count", 0)),
            failed_tool_call_count=int(data.get("failed_tool_call_count", 0)),
        )


@dataclass(slots=True)
class Run:
    id: str
    tenant_id: str
    agent_id: str
    adapter: str
    status: str
    input: dict[str, Any]
    created_at: str
    updated_at: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    usage: RunUsage = field(default_factory=RunUsage)
    project_id: str | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    messages_truncated: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Run:
        return cls(
            id=str(data["id"]),
            tenant_id=str(data["tenant_id"]),
            project_id=data.get("project_id"),
            agent_id=str(data["agent_id"]),
            adapter=str(data["adapter"]),
            status=str(data["status"]),
            input=dict(data.get("input") or {}),
            output=data.get("output"),
            error=data.get("error"),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            steps=list(data.get("steps") or []),
            messages=list(data.get("messages") or []),
            messages_truncated=bool(data.get("messages_truncated", False)),
            checkpoints=list(data.get("checkpoints") or []),
            usage=RunUsage.from_dict(data.get("usage")),
        )


@dataclass(slots=True)
class RunCreateRequest:
    agent_id: str
    input: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    adapter: str | None = None
