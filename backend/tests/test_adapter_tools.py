"""Tests for the standardized adapter tool surface."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from app.adapters.adapter_tools import (
    AdapterToolSurface,
    build_tool_arguments,
    open_tool_surface,
)
from app.adapters.base import AdapterContext
from app.adapters.tool_registry import ToolDefinition, get_tool

_FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


class _RecordingContext(AdapterContext):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        super().__init__(
            run_id="01TEST",
            agent_id="01AGENT",
            agent_config={},
            input={"prompt": "hello"},
            emit=self._emit,
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


def test_build_tool_arguments_from_schema():
    tool = get_tool("echo")
    args = build_tool_arguments(tool, {"input": "hi", "reply": "there"})
    assert args["text"] == "there"


@pytest.mark.asyncio
async def test_adapter_tool_surface_builtin_execute():
    ctx = _RecordingContext()
    surface = await AdapterToolSurface.open({"tools": ["echo"]}, ["echo"])
    try:
        result = await surface.execute(
            ctx, step_index=0, name="echo", arguments={"text": "ping"}
        )
        assert result == {"text": "ping"}
        started = [d for e, d in ctx.events if e == "tool_call.started"]
        completed = [d for e, d in ctx.events if e == "tool_call.completed"]
        assert len(started) == 1
        assert started[0]["name"] == "echo"
        assert len(completed) == 1
        assert completed[0]["result"] == {"text": "ping"}
    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_adapter_tool_surface_mcp_tool():
    ctx = _RecordingContext()
    surface = await AdapterToolSurface.open(
        {"mcp_servers": [_mcp_server_config()]},
        ["mcp/echo/ping"],
    )
    try:
        assert len(surface.tools) == 1
        result = await surface.execute(
            ctx,
            step_index=1,
            name="mcp/echo/ping",
            arguments={"message": "hi"},
        )
        assert result["text"] == "hi"
        assert any(e == "tool_call.started" for e, _ in ctx.events)
        assert any(e == "tool_call.completed" for e, _ in ctx.events)
    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_open_tool_surface_context_manager():
    async with open_tool_surface({"tools": ["echo"]}, ["echo"]) as surface:
        tool = surface.lookup("echo")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "echo"
