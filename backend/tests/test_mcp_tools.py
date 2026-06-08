"""MCP tool bridge and LangGraph integration tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from app.adapters.base import AdapterContext
from app.adapters.langgraph_adapter import LangGraphAdapter
from app.adapters.mcp_client import (
    mcp_tool_key,
    parse_mcp_servers,
    parse_mcp_tool_key,
    serialize_call_tool_result,
)
from app.adapters.mcp_tools import resolve_run_tools
from app.models.run import RunStatus

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


def test_parse_mcp_servers():
    servers = parse_mcp_servers({"mcp_servers": [_mcp_server_config()]})
    assert len(servers) == 1
    assert servers[0].name == "echo"
    assert servers[0].command == sys.executable


def test_mcp_tool_key_roundtrip():
    key = mcp_tool_key("echo", "ping")
    assert key == "mcp/echo/ping"
    assert parse_mcp_tool_key(key) == ("echo", "ping")


@pytest.mark.asyncio
async def test_resolve_run_tools_lists_mcp_tool():
    resolver = await resolve_run_tools(
        {"mcp_servers": [_mcp_server_config()]},
        ["mcp/echo/ping"],
    )
    try:
        assert len(resolver.tools) == 1
        assert resolver.tools[0].name == "mcp/echo/ping"
        result = await resolver.tools[0].handler({"message": "hi"})
        assert result["text"] == "hi"
    finally:
        await resolver.close()


@pytest.mark.asyncio
async def test_resolve_run_tools_auto_register():
    resolver = await resolve_run_tools(
        {
            "mcp_servers": [_mcp_server_config()],
            "mcp_auto_register": True,
        },
        [],
    )
    try:
        names = {tool.name for tool in resolver.tools}
        assert "mcp/echo/ping" in names
        assert "mcp/echo/add" in names
    finally:
        await resolver.close()


@pytest.mark.asyncio
async def test_langgraph_mcp_tool_writes_tool_call_events():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = {
        "model": "openai/gpt-4o-mini",
        "mcp_servers": [_mcp_server_config()],
        "tools": ["mcp/echo/ping"],
        "graph": {
            "nodes": [
                {"id": "draft", "type": "model"},
                {"id": "ping_step", "type": "tool", "tool": "mcp/echo/ping"},
            ],
            "edges": [
                ["__start__", "draft"],
                ["draft", "ping_step"],
                ["ping_step", "__end__"],
            ],
        },
    }
    result = await adapter.run(ctx)
    assert result.status == RunStatus.SUCCEEDED

    tool_started = [
        data
        for event, data in ctx.events
        if event == "tool_call.started"
    ]
    tool_completed = [
        data
        for event, data in ctx.events
        if event == "tool_call.completed"
    ]
    assert len(tool_started) == 1
    assert tool_started[0]["name"] == "mcp/echo/ping"
    assert len(tool_completed) == 1
    assert tool_completed[0]["result"]["text"]


def test_serialize_call_tool_result_text():
    from mcp.types import CallToolResult, TextContent

    result = serialize_call_tool_result(
        CallToolResult(content=[TextContent(type="text", text="ok")])
    )
    assert result["text"] == "ok"
    assert result["content"][0]["text"] == "ok"
