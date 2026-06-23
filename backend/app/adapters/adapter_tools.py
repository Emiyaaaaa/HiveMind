"""Standardized tool surface for orchestrator adapters.

All adapters resolve builtin registry tools and MCP-backed tools through
``AdapterToolSurface``. Invocations emit ``tool_call.started`` /
``tool_call.completed`` so the runtime persists ``ToolCall`` rows the same way
for every framework integration.

Agent config example::

    {
      "tools": ["echo", "mcp/echo/ping"],
      "mcp_servers": [
        {
          "name": "echo",
          "transport": "stdio",
          "command": "python",
          "args": ["path/to/mcp_server.py"]
        }
      ],
      "mcp_auto_register": false
    }
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.adapters.base import AdapterContext
from app.adapters.mcp_tools import RunToolResolver, resolve_run_tools
from app.adapters.tool_registry import ToolDefinition, get_tool


def tool_schemas_from_definitions(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """OpenAI-compatible function schemas from resolved tool definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or f"Invoke the {tool.name} tool.",
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


def build_tool_arguments(tool: ToolDefinition, state: dict[str, Any]) -> dict[str, Any]:
    """Build tool arguments from graph state using the tool parameter schema."""
    text = str(state.get("reply") or state.get("input", ""))
    props = (tool.parameters or {}).get("properties") or {}
    if not props:
        return {"text": text, "input": state.get("input", "")}

    arguments: dict[str, Any] = {}
    for name, spec in props.items():
        if name in ("text", "message", "prompt", "query", "input"):
            arguments[name] = text if name != "input" else state.get("input", "")
        elif spec.get("type") == "string":
            arguments[name] = text
        elif spec.get("type") == "integer":
            try:
                arguments[name] = int(text)
            except (TypeError, ValueError):
                arguments[name] = 0
    return arguments or {"text": text, "input": state.get("input", "")}


@dataclass
class AdapterToolSurface:
    """Resolved builtin + MCP tools for one adapter run."""

    tools: list[ToolDefinition]
    _resolver: RunToolResolver

    @classmethod
    async def open(
        cls,
        config: dict[str, Any],
        tool_keys: list[str] | None = None,
    ) -> AdapterToolSurface:
        """Resolve tools from agent config and connect MCP servers when configured."""
        keys = list(tool_keys if tool_keys is not None else config.get("tools") or [])
        resolver = await resolve_run_tools(config, keys)
        return cls(tools=resolver.tools, _resolver=resolver)

    async def close(self) -> None:
        await self._resolver.close()

    def schemas(self) -> list[dict[str, Any]]:
        return tool_schemas_from_definitions(self.tools)

    def lookup(self, name: str) -> ToolDefinition:
        """Return a resolved tool by registry key, falling back to builtins."""
        for tool in self.tools:
            if tool.name == name:
                return tool
        return get_tool(name)

    async def execute(
        self,
        ctx: AdapterContext,
        *,
        step_index: int,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke a tool and emit standardized ToolCall lifecycle events."""
        tool = self.lookup(name)
        await ctx.emit_tool_call_started(
            step_index=step_index, name=tool.name, arguments=arguments
        )
        try:
            result = await tool.handler(arguments)
            if not isinstance(result, dict):
                result = {"result": result}
            await ctx.emit_tool_call_completed(
                step_index=step_index, name=tool.name, result=result
            )
            return result
        except Exception as exc:
            await ctx.emit_tool_call_completed(
                step_index=step_index, name=tool.name, error=str(exc)
            )
            raise


@asynccontextmanager
async def open_tool_surface(
    config: dict[str, Any],
    tool_keys: list[str] | None = None,
) -> AsyncIterator[AdapterToolSurface]:
    """Context manager that closes MCP sessions on exit."""
    surface = await AdapterToolSurface.open(config, tool_keys)
    try:
        yield surface
    finally:
        await surface.close()
