"""Bridge MCP server tools into adapter tool resolution.

Agent config example::

    {
      "mcp_servers": [
        {
          "name": "echo",
          "transport": "stdio",
          "command": "python",
          "args": ["tests/fixtures/mcp_echo_server.py"]
        }
      ],
      "tools": ["mcp/echo/ping"],
      "mcp_auto_register": false
    }

When ``mcp_auto_register`` is true, every tool exposed by configured MCP
servers is registered automatically (still filtered by ``tools`` when that
list is non-empty).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.adapters.mcp_client import (
    McpSessionManager,
    is_mcp_tool_key,
    mcp_tool_key,
    parse_mcp_servers,
    parse_mcp_tool_key,
)
from app.adapters.tool_registry import ToolDefinition, resolve_tools
from app.core.logging import get_logger

logger = get_logger("adapter.mcp_tools")

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class RunToolResolver:
    """Resolved builtin + MCP tools for one adapter run."""

    tools: list[ToolDefinition]
    mcp_manager: McpSessionManager | None = None

    async def close(self) -> None:
        if self.mcp_manager is not None:
            await self.mcp_manager.close()


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


async def resolve_run_tools(
    config: dict[str, Any],
    keys: list[str],
) -> RunToolResolver:
    """Resolve builtin registry tools plus MCP-backed tools for a run."""
    try:
        mcp_servers = parse_mcp_servers(config)
    except ValueError as exc:
        raise KeyError(str(exc)) from exc

    auto_register = bool(config.get("mcp_auto_register"))
    mcp_keys = [key for key in keys if is_mcp_tool_key(key)]
    builtin_keys = [key for key in keys if not is_mcp_tool_key(key)]

    builtin_tools = resolve_tools(builtin_keys) if builtin_keys else []

    if not mcp_servers:
        if mcp_keys:
            raise KeyError(
                "MCP tools requested but no mcp_servers configured in agent.config"
            )
        return RunToolResolver(tools=builtin_tools)

    manager = McpSessionManager(mcp_servers)
    try:
        await manager.connect_all()
        mcp_tool_keys = await _collect_mcp_tool_keys(
            manager, config, mcp_keys, auto_register
        )
        mcp_tools = await _build_mcp_tool_definitions(manager, mcp_tool_keys)
    except Exception:
        await manager.close()
        raise

    return RunToolResolver(tools=builtin_tools + mcp_tools, mcp_manager=manager)


async def _collect_mcp_tool_keys(
    manager: McpSessionManager,
    config: dict[str, Any],
    explicit_keys: list[str],
    auto_register: bool,
) -> list[str]:
    if auto_register:
        keys: list[str] = []
        for server_name in manager.server_names:
            for tool in await manager.list_tools(server_name):
                keys.append(mcp_tool_key(server_name, tool.name))
        if explicit_keys:
            allowed = set(explicit_keys)
            keys = [key for key in keys if key in allowed]
        return sorted(set(keys))

    if not explicit_keys:
        return []

    needed_servers = {parse_mcp_tool_key(key)[0] for key in explicit_keys}
    unknown_servers = needed_servers - set(manager.server_names)
    if unknown_servers:
        missing = ", ".join(sorted(unknown_servers))
        raise KeyError(f"Unknown MCP server(s): {missing}")

    return explicit_keys


async def _build_mcp_tool_definitions(
    manager: McpSessionManager,
    keys: list[str],
) -> list[ToolDefinition]:
    definitions: list[ToolDefinition] = []
    for key in keys:
        server_name, tool_name = parse_mcp_tool_key(key)
        meta = await manager.get_tool_meta(server_name, tool_name)
        handler = _make_mcp_handler(manager, server_name, tool_name)
        parameters = getattr(meta, "inputSchema", None) or {
            "type": "object",
            "properties": {},
        }
        definitions.append(
            ToolDefinition(
                name=key,
                handler=handler,
                description=getattr(meta, "description", None) or "",
                parameters=parameters,
            )
        )
        logger.debug(
            "mcp_tool.registered",
            key=key,
            server=server_name,
            tool=tool_name,
        )
    return definitions


def _make_mcp_handler(
    manager: McpSessionManager,
    server_name: str,
    tool_name: str,
) -> ToolHandler:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        return await manager.call_tool(server_name, tool_name, arguments)

    return handler
