"""Built-in and pluggable tools for orchestrator adapters.

Adapters resolve tool keys from ``agent.config.tools`` through this registry.
Register custom tools at process startup (e.g. in ``app/adapters/__init__.py``)
before workers begin consuming jobs.

Example::

    from app.adapters.tool_registry import register_tool

    async def search_web(arguments: dict) -> dict:
        return {"results": []}

    register_tool("search_web", search_web, description="Search the public web.")
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class ToolDefinition:
    """Metadata and handler for a registered tool."""

    name: str
    handler: ToolHandler
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


_registry: dict[str, ToolDefinition] = {}


def register_tool(
    name: str,
    handler: ToolHandler,
    *,
    description: str = "",
    parameters: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> None:
    """Register a tool handler under ``name``.

    Raises ``ValueError`` if the name already exists and ``overwrite`` is false.
    """
    if name in _registry and not overwrite:
        raise ValueError(f"Tool already registered: {name!r}")
    _registry[name] = ToolDefinition(
        name=name,
        handler=handler,
        description=description,
        parameters=parameters or {"type": "object", "properties": {}},
    )


def get_tool(name: str) -> ToolDefinition:
    if name not in _registry:
        raise KeyError(f"Unknown tool: {name!r}")
    return _registry[name]


def resolve_tools(keys: list[str]) -> list[ToolDefinition]:
    """Return tool definitions for the given registry keys, preserving order."""
    missing = [key for key in keys if key not in _registry]
    if missing:
        raise KeyError(f"Unknown tool(s): {', '.join(missing)}")
    return [_registry[key] for key in keys]


def list_tools() -> list[str]:
    return sorted(_registry)


def tool_schemas(keys: list[str]) -> list[dict[str, Any]]:
    """OpenAI-compatible function schemas for the resolved tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or f"Invoke the {tool.name} tool.",
                "parameters": tool.parameters,
            },
        }
        for tool in resolve_tools(keys)
    ]


async def _echo(arguments: dict[str, Any]) -> dict[str, Any]:
    text = arguments.get("text", arguments.get("input", ""))
    return {"text": text}


async def _noop(_arguments: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True}


def _register_builtins() -> None:
    register_tool(
        "echo",
        _echo,
        description="Echo the input text back unchanged.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo."},
            },
        },
        overwrite=True,
    )
    register_tool(
        "noop",
        _noop,
        description="No-op placeholder for wiring tests.",
        overwrite=True,
    )


_register_builtins()
