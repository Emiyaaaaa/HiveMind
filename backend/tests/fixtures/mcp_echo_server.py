"""Minimal MCP server used by integration tests."""

from __future__ import annotations

import asyncio

import mcp_types as types
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

_TOOLS = [
    types.Tool(
        name="ping",
        description="Echo a message back.",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
    ),
    types.Tool(
        name="add",
        description="Add two integers.",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    ),
]


async def _list_tools(_ctx, _params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=_TOOLS)


async def _call_tool(_ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    arguments = params.arguments or {}
    if params.name == "ping":
        message = str(arguments.get("message", "ping"))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)]
        )
    if params.name == "add":
        total = int(arguments.get("a", 0)) + int(arguments.get("b", 0))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(total))]
        )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"unknown tool {params.name!r}")],
        is_error=True,
    )


async def _main() -> None:
    server = Server(
        "echo-test",
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_main())
