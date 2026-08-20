"""Tests for the MCP tool adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from app.adapters.base import AdapterContext
from app.adapters.mcp_adapter import McpAdapter, _parse_tool_calls
from app.models.run import RunStatus

_FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


class _RecordingContext(AdapterContext):
    def __init__(self, **kwargs: Any) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        super().__init__(
            run_id="01TEST",
            agent_id="01AGENT",
            agent_config=kwargs.pop("agent_config", {}),
            input=kwargs.pop("input", {"prompt": "hello"}),
            emit=self._emit,
            **kwargs,
        )

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def _mcp_server_config() -> dict[str, Any]:
    return {
        "name": "echo",
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(_FIXTURE_SERVER)],
    }


def test_parse_tool_calls_from_input():
    calls = _parse_tool_calls({}, {"tool": "mcp/echo/ping", "arguments": {"message": "hi"}})
    assert calls == [{"tool": "mcp/echo/ping", "arguments": {"message": "hi"}}]


def test_parse_tool_calls_from_batch():
    calls = _parse_tool_calls(
        {},
        {
            "calls": [
                {"tool": "mcp/echo/ping", "arguments": {"message": "a"}},
                {"tool": "mcp/echo/add", "arguments": {"a": 1, "b": 2}},
            ]
        },
    )
    assert len(calls) == 2


def test_parse_tool_calls_from_config_steps():
    calls = _parse_tool_calls(
        {"steps": [{"tool": "mcp/echo/ping", "arguments": {"message": "x"}}]},
        {},
    )
    assert calls[0]["tool"] == "mcp/echo/ping"


def test_parse_tool_calls_requires_input():
    with pytest.raises(ValueError, match="requires agent.config.steps"):
        _parse_tool_calls({}, {})


@pytest.mark.asyncio
async def test_mcp_adapter_single_tool_call():
    adapter = McpAdapter()
    ctx = _RecordingContext(
        agent_config={"mcp_servers": [_mcp_server_config()]},
        input={"tool": "mcp/echo/ping", "arguments": {"message": "hello"}},
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatus.SUCCEEDED
    assert result.output["result"]["text"] == "hello"

    started = [d for e, d in ctx.events if e == "tool_call.started"]
    completed = [d for e, d in ctx.events if e == "tool_call.completed"]
    assert len(started) == 1
    assert started[0]["name"] == "mcp/echo/ping"
    assert len(completed) == 1
    assert completed[0]["result"]["text"] == "hello"


@pytest.mark.asyncio
async def test_mcp_adapter_batch_calls():
    adapter = McpAdapter()
    ctx = _RecordingContext(
        agent_config={"mcp_servers": [_mcp_server_config()]},
        input={
            "calls": [
                {"tool": "mcp/echo/ping", "arguments": {"message": "a"}},
                {"tool": "mcp/echo/add", "arguments": {"a": 2, "b": 3}},
            ]
        },
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatus.SUCCEEDED
    assert result.output["count"] == 2
    assert result.output["calls"][1]["result"]["text"] == "5"

    tool_events = [e for e, _ in ctx.events if e.startswith("tool_call.")]
    assert len(tool_events) == 4


@pytest.mark.asyncio
async def test_mcp_adapter_rejects_non_mcp_tool():
    adapter = McpAdapter()
    ctx = _RecordingContext(
        agent_config={"mcp_servers": [_mcp_server_config()]},
        input={"tool": "echo", "arguments": {"text": "hi"}},
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatus.FAILED
    assert "mcp/" in (result.error or "")


@pytest.mark.asyncio
async def test_mcp_adapter_config_steps():
    adapter = McpAdapter()
    ctx = _RecordingContext(
        agent_config={
            "mcp_servers": [_mcp_server_config()],
            "steps": [{"tool": "mcp/echo/ping", "arguments": {"message": "from-config"}}],
        },
        input={},
    )
    result = await adapter.run(ctx)
    assert result.status == RunStatus.SUCCEEDED
    assert result.output["result"]["text"] == "from-config"
