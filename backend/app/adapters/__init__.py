"""Pluggable orchestrator adapters.

Adapters are the bridge between AgentFlow's runtime tables and a concrete
multi-agent framework (LangGraph, AutoGen, CrewAI, custom). Add a new adapter
by subclassing `OrchestratorAdapter` and registering it via
`register_adapter`.
"""

from app.adapters.base import (
    AdapterContext,
    OrchestratorAdapter,
    get_adapter,
    register_adapter,
)
from app.adapters import tool_registry as _tool_registry  # noqa: F401 - builtins
from app.adapters.echo_adapter import EchoAdapter
from app.adapters.langgraph_adapter import LangGraphAdapter
from app.adapters.tool_registry import (
    ToolDefinition,
    get_tool,
    list_tools,
    register_tool,
    resolve_tools,
)

register_adapter("echo", EchoAdapter())
register_adapter("langgraph", LangGraphAdapter())

__all__ = [
    "AdapterContext",
    "EchoAdapter",
    "LangGraphAdapter",
    "OrchestratorAdapter",
    "ToolDefinition",
    "get_adapter",
    "get_tool",
    "list_tools",
    "register_adapter",
    "register_tool",
    "resolve_tools",
]
