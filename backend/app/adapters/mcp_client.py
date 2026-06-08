"""MCP client transport and per-run session management.

Connects to MCP servers over stdio, SSE, or Streamable HTTP and exposes
``list_tools`` / ``call_tool`` for the tool-registry bridge.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.logging import get_logger

logger = get_logger("adapter.mcp")

MCP_TOOL_PREFIX = "mcp/"
TransportKind = Literal["stdio", "sse", "http"]


@dataclass(frozen=True)
class McpServerConfig:
    """Connection parameters for one MCP server."""

    name: str
    transport: TransportKind = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: str | None = None


def parse_mcp_servers(raw_config: dict[str, Any]) -> list[McpServerConfig]:
    """Parse ``agent.config.mcp_servers`` into connection specs."""
    servers: list[McpServerConfig] = []
    for entry in raw_config.get("mcp_servers") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            raise ValueError("mcp_servers entry requires 'name'")
        transport = str(entry.get("transport", "stdio"))
        if transport not in ("stdio", "sse", "http"):
            raise ValueError(
                f"mcp server {name!r}: unsupported transport {transport!r}"
            )
        servers.append(
            McpServerConfig(
                name=str(name),
                transport=transport,  # type: ignore[arg-type]
                command=entry.get("command"),
                args=[str(a) for a in entry.get("args") or []],
                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
                cwd=entry.get("cwd"),
                url=entry.get("url"),
            )
        )
    return servers


def mcp_tool_key(server_name: str, tool_name: str) -> str:
    """Registry key for an MCP-backed tool."""
    return f"{MCP_TOOL_PREFIX}{server_name}/{tool_name}"


def parse_mcp_tool_key(key: str) -> tuple[str, str]:
    """Split ``mcp/{server}/{tool}`` into server and tool names."""
    if not key.startswith(MCP_TOOL_PREFIX):
        raise ValueError(f"Not an MCP tool key: {key!r}")
    remainder = key[len(MCP_TOOL_PREFIX) :]
    if "/" not in remainder:
        raise ValueError(f"MCP tool key must be mcp/{{server}}/{{tool}}: {key!r}")
    server_name, tool_name = remainder.split("/", 1)
    if not server_name or not tool_name:
        raise ValueError(f"Invalid MCP tool key: {key!r}")
    return server_name, tool_name


def is_mcp_tool_key(key: str) -> bool:
    return key.startswith(MCP_TOOL_PREFIX)


def serialize_call_tool_result(result: Any) -> dict[str, Any]:
    """Normalize an MCP ``CallToolResult`` into a JSON-friendly dict."""
    content_blocks: list[dict[str, Any]] = []
    for block in getattr(result, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            content_blocks.append({"type": "text", "text": block.text})
        elif block_type == "image":
            content_blocks.append(
                {
                    "type": "image",
                    "mimeType": block.mimeType,
                    "data": block.data,
                }
            )
        elif hasattr(block, "model_dump"):
            content_blocks.append(block.model_dump())
        else:
            content_blocks.append({"type": str(block_type), "raw": str(block)})

    payload: dict[str, Any] = {"content": content_blocks}
    if getattr(result, "isError", False):
        payload["is_error"] = True
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload["structured"] = structured

    texts = [b["text"] for b in content_blocks if b.get("type") == "text"]
    if texts:
        payload["text"] = "\n".join(texts)
    return payload


class McpSessionManager:
    """Keeps live MCP sessions open for the duration of one adapter run."""

    def __init__(self, servers: list[McpServerConfig]) -> None:
        self._servers = {server.name: server for server in servers}
        self._sessions: dict[str, Any] = {}
        self._tool_cache: dict[str, dict[str, Any]] = {}
        self._stack = AsyncExitStack()

    @property
    def server_names(self) -> list[str]:
        return sorted(self._servers)

    async def connect_all(self) -> None:
        for name, spec in self._servers.items():
            if name in self._sessions:
                continue
            session = await self._connect_server(spec)
            self._sessions[name] = session
            logger.info("mcp_server.connected", server=name, transport=spec.transport)

    async def _connect_server(self, spec: McpServerConfig) -> Any:
        try:
            from mcp import ClientSession
        except ImportError as exc:  # pragma: no cover - dep guard
            raise RuntimeError(
                "mcp is not installed; add it to your environment."
            ) from exc

        if spec.transport == "stdio":
            if not spec.command:
                raise ValueError(
                    f"mcp server {spec.name!r}: stdio transport requires 'command'"
                )
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=spec.command,
                args=spec.args,
                env=spec.env,
                cwd=spec.cwd,
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif spec.transport == "sse":
            if not spec.url:
                raise ValueError(
                    f"mcp server {spec.name!r}: sse transport requires 'url'"
                )
            from mcp.client.sse import sse_client

            read, write = await self._stack.enter_async_context(
                sse_client(spec.url)
            )
        else:
            if not spec.url:
                raise ValueError(
                    f"mcp server {spec.name!r}: http transport requires 'url'"
                )
            from mcp.client.streamable_http import streamablehttp_client

            read, write, _get_session_id = await self._stack.enter_async_context(
                streamablehttp_client(spec.url)
            )

        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def list_tools(self, server_name: str) -> list[Any]:
        session = await self._require_session(server_name)
        response = await session.list_tools()
        return list(response.tools)

    async def get_tool_meta(self, server_name: str, tool_name: str) -> Any:
        cached = self._tool_cache.get(server_name)
        if cached is None:
            tools = await self.list_tools(server_name)
            cached = {tool.name: tool for tool in tools}
            self._tool_cache[server_name] = cached
        if tool_name not in cached:
            raise KeyError(
                f"Unknown MCP tool {tool_name!r} on server {server_name!r}"
            )
        return cached[tool_name]

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        session = await self._require_session(server_name)
        result = await session.call_tool(tool_name, arguments)
        return serialize_call_tool_result(result)

    async def _require_session(self, server_name: str) -> Any:
        if server_name not in self._servers:
            raise KeyError(f"Unknown MCP server: {server_name!r}")
        if server_name not in self._sessions:
            await self.connect_all()
        session = self._sessions.get(server_name)
        if session is None:
            raise RuntimeError(f"MCP server {server_name!r} is not connected")
        return session

    async def close(self) -> None:
        await self._stack.aclose()
        self._sessions.clear()
        self._tool_cache.clear()
