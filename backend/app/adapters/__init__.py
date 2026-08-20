"""Pluggable orchestrator adapters.

Adapters are the bridge between AgentFlow's runtime tables and a concrete
multi-agent framework (LangGraph, AutoGen, CrewAI, custom). Add a new adapter
by subclassing `OrchestratorAdapter` and registering it via
`register_adapter`.
"""

from app.adapters import tool_registry as _tool_registry  # noqa: F401 - builtins
from app.adapters.adapter_tools import (
    AdapterToolSurface,
    build_tool_arguments,
    open_tool_surface,
    tool_schemas_from_definitions,
)
from app.adapters.base import (
    AdapterContext,
    OrchestratorAdapter,
    get_adapter,
    register_adapter,
)
from app.adapters.discovery import AdapterPluginError, load_adapter_plugins
from app.adapters.echo_adapter import EchoAdapter
from app.adapters.langgraph_adapter import LangGraphAdapter
from app.adapters.mcp_adapter import McpAdapter
from app.adapters.mcp_client import (
    McpServerConfig,
    McpSessionManager,
    parse_mcp_servers,
)
from app.adapters.mcp_tools import RunToolResolver, resolve_run_tools
from app.adapters.tool_registry import (
    ToolDefinition,
    get_tool,
    list_tools,
    register_tool,
    resolve_tools,
)

register_adapter("echo", EchoAdapter())
register_adapter("langgraph", LangGraphAdapter())
register_adapter("mcp", McpAdapter())

__all__ = [
    "AdapterContext",
    "AdapterPluginError",
    "AdapterToolSurface",
    "EchoAdapter",
    "LangGraphAdapter",
    "McpAdapter",
    "McpServerConfig",
    "McpSessionManager",
    "OrchestratorAdapter",
    "RunToolResolver",
    "ToolDefinition",
    "build_tool_arguments",
    "get_adapter",
    "get_tool",
    "list_tools",
    "load_adapter_plugins",
    "open_tool_surface",
    "parse_mcp_servers",
    "register_adapter",
    "register_tool",
    "resolve_run_tools",
    "resolve_tools",
    "tool_schemas_from_definitions",
]
