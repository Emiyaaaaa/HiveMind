"""Data models aligned with openapi/openapi.yaml."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


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
    thread_id: str | None = None


@dataclass(slots=True)
class MessagePage:
    """One page of a run or thread transcript.

    ``next_cursor`` is an int for ``GET /v1/runs/{id}/messages`` (exclusive
    upper ``index`` bound) and an opaque string for
    ``GET /v1/threads/{id}/messages``; pass it back verbatim to load older
    messages. ``None`` / ``has_more=False`` means the oldest page was reached.
    """

    items: list[dict[str, Any]]
    next_cursor: int | str | None
    has_more: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MessagePage:
        return cls(
            items=list(data.get("items") or []),
            next_cursor=data.get("next_cursor"),
            has_more=bool(data.get("has_more", False)),
        )


@dataclass(slots=True)
class Thread:
    id: str
    tenant_id: str
    agent_id: str
    created_at: str
    updated_at: str
    project_id: str | None = None
    user_id: str | None = None
    title: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Thread:
        return cls(
            id=str(data["id"]),
            tenant_id=str(data["tenant_id"]),
            project_id=data.get("project_id"),
            agent_id=str(data["agent_id"]),
            user_id=data.get("user_id"),
            title=data.get("title"),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )


@dataclass(slots=True)
class RunAuditEvent:
    """Cancel/resume governance record from ``GET /v1/runs/{id}/audit``."""

    id: str
    run_id: str
    action: str
    actor_subject: str
    actor_role: str
    created_at: str
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunAuditEvent:
        return cls(
            id=str(data["id"]),
            run_id=str(data["run_id"]),
            action=str(data["action"]),
            actor_subject=str(data.get("actor_subject") or ""),
            actor_role=str(data.get("actor_role") or ""),
            detail=dict(data.get("detail") or {}),
            created_at=str(data["created_at"]),
        )
