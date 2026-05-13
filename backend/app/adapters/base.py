"""Orchestrator adapter contract.

Adapters expose a single async `run` method. The runtime gives them an
`AdapterContext` that is the adapter's only writable surface: every state
change must go through `ctx.emit_*` so the database and event bus stay in
sync. Adapters must not import SQLAlchemy or hit the event bus directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.models.run import RunStatus
from app.schemas.run import EventType

EmitCallback = Callable[[EventType, dict[str, Any]], Awaitable[None]]


@dataclass
class AdapterContext:
    """Per-run state exposed to adapters.

    The orchestrator implementation should call `emit` to publish lifecycle
    events. The runtime service translates each event into database writes
    plus an SSE broadcast.
    """

    run_id: str
    agent_id: str
    agent_config: dict[str, Any]
    input: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    emit: EmitCallback = field(
        default=None  # type: ignore[assignment]
    )

    async def emit_step_started(self, *, index: int, node: str, **data: Any) -> None:
        await self.emit("step.started", {"index": index, "node": node, **data})

    async def emit_step_completed(
        self, *, index: int, node: str, output: dict[str, Any] | None = None, **data: Any
    ) -> None:
        await self.emit(
            "step.completed",
            {"index": index, "node": node, "output": output, **data},
        )

    async def emit_step_failed(
        self, *, index: int, node: str, error: str, **data: Any
    ) -> None:
        await self.emit(
            "step.failed", {"index": index, "node": node, "error": error, **data}
        )

    async def emit_message(
        self, *, role: str, content: str, name: str | None = None, **extra: Any
    ) -> None:
        await self.emit(
            "message.created",
            {"role": role, "content": content, "name": name, "extra": extra},
        )

    async def emit_tool_call_started(
        self, *, step_index: int, name: str, arguments: dict[str, Any]
    ) -> None:
        await self.emit(
            "tool_call.started",
            {"step_index": step_index, "name": name, "arguments": arguments},
        )

    async def emit_tool_call_completed(
        self,
        *,
        step_index: int,
        name: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        await self.emit(
            "tool_call.completed",
            {
                "step_index": step_index,
                "name": name,
                "result": result,
                "error": error,
            },
        )

    async def emit_log(self, message: str, **fields: Any) -> None:
        await self.emit(
            "log",
            {"message": message, "at": datetime.now(UTC).isoformat(), **fields},
        )


@dataclass
class AdapterResult:
    """Final result of an adapter `run`."""

    status: RunStatus
    output: dict[str, Any] | None = None
    error: str | None = None


class OrchestratorAdapter(ABC):
    """Implement this to plug a new multi-agent framework into AgentFlow."""

    name: str = "base"

    @abstractmethod
    async def run(self, ctx: AdapterContext) -> AdapterResult:
        """Execute one run end-to-end.

        Adapters should:
        - emit lifecycle events (`step.started`, `step.completed`, ...) via
          `ctx.emit_*` helpers,
        - return an `AdapterResult` describing the terminal outcome,
        - surface errors as `AdapterResult(status=FAILED, error=...)` rather
          than letting exceptions escape (the runtime will still convert
          uncaught exceptions, but explicit returns produce nicer audit logs).
        """


_registry: dict[str, OrchestratorAdapter] = {}


def register_adapter(name: str, adapter: OrchestratorAdapter) -> None:
    adapter.name = name
    _registry[name] = adapter


def get_adapter(name: str) -> OrchestratorAdapter:
    if name not in _registry:
        raise KeyError(f"Unknown orchestrator adapter: {name!r}")
    return _registry[name]


def list_adapters() -> list[str]:
    return sorted(_registry)
