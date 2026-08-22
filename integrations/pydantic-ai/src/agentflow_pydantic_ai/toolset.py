"""Expose AgentFlow-managed tools as a per-run PydanticAI toolset."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any

from app.adapters.adapter_tools import AdapterToolSurface
from app.adapters.base import AdapterContext
from app.adapters.tool_registry import ToolDefinition as AgentFlowToolDefinition
from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition as PydanticAIToolDefinition
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from pydantic_core import SchemaValidator, core_schema

_MAX_TOOL_NAME_LENGTH = 64
_SAFE_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_UNSAFE_TOOL_NAME = re.compile(r"[^A-Za-z0-9_-]+")
_ARGUMENTS_VALIDATOR = SchemaValidator(core_schema.dict_schema())


def pydantic_tool_name(name: str) -> str:
    """Return a provider-safe name while keeping common registry keys readable."""
    if name and len(name) <= _MAX_TOOL_NAME_LENGTH and _SAFE_TOOL_NAME.fullmatch(name):
        return name

    normalized = _UNSAFE_TOOL_NAME.sub("__", name).strip("_") or "tool"
    if len(normalized) <= _MAX_TOOL_NAME_LENGTH:
        return normalized

    digest = hashlib.sha256(name.encode()).hexdigest()[:8]
    prefix_length = _MAX_TOOL_NAME_LENGTH - len(digest) - 1
    return f"{normalized[:prefix_length]}_{digest}"


class AgentFlowToolset(AbstractToolset[Any]):
    """Translate and execute tools resolved through ``AdapterToolSurface``."""

    def __init__(
        self,
        surface: AdapterToolSurface,
        adapter_ctx: AdapterContext,
        step_index: int,
    ) -> None:
        self._surface = surface
        self._adapter_ctx = adapter_ctx
        self._step_index = step_index
        self._tools: dict[str, AgentFlowToolDefinition] = {}

        for tool in surface.tools:
            exposed_name = pydantic_tool_name(tool.name)
            existing = self._tools.get(exposed_name)
            if existing is not None and existing.name != tool.name:
                raise ValueError(
                    "AgentFlow tool names "
                    f"{existing.name!r} and {tool.name!r} both map to "
                    f"PydanticAI name {exposed_name!r}"
                )
            self._tools[exposed_name] = tool

    @property
    def id(self) -> str:
        return "agentflow-runtime"

    @property
    def exposed_names(self) -> frozenset[str]:
        """Names visible to PydanticAI and model providers for this run."""
        return frozenset(self._tools)

    def owns(self, name: str | None) -> bool:
        """Return whether an event belongs to an AgentFlow-managed tool."""
        return name in self._tools if name is not None else False

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        del ctx
        return {
            exposed_name: ToolsetTool(
                toolset=self,
                tool_def=PydanticAIToolDefinition(
                    name=exposed_name,
                    description=tool.description or f"Invoke the {tool.name} tool.",
                    parameters_json_schema=deepcopy(tool.parameters)
                    or {"type": "object", "properties": {}},
                    metadata={"agentflow_tool_name": tool.name},
                ),
                max_retries=0,
                args_validator=_ARGUMENTS_VALIDATOR,
            )
            for exposed_name, tool in self._tools.items()
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[Any],
        tool: ToolsetTool[Any],
    ) -> Any:
        del ctx, tool
        definition = self._tools.get(name)
        if definition is None:
            raise KeyError(f"Unknown AgentFlow tool: {name!r}")
        return await self._surface.execute(
            self._adapter_ctx,
            step_index=self._step_index,
            name=definition.name,
            arguments=tool_args,
        )
