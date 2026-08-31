"""Bridge AgentFlow-managed tools into AutoGen ``FunctionTool`` instances."""

from __future__ import annotations

import json
from typing import Annotated, Any, Callable

from app.adapters.adapter_tools import AdapterToolSurface
from app.adapters.base import AdapterContext
from app.adapters.tool_registry import ToolDefinition
from autogen_core.tools import FunctionTool


def build_function_tools(
    surface: AdapterToolSurface,
    ctx: AdapterContext,
    *,
    step_index: int,
    on_tool_error: Callable[[str], None] | None = None,
) -> tuple[list[FunctionTool], frozenset[str]]:
    """Create AutoGen tools that delegate execution to ``AdapterToolSurface``."""
    tools: list[FunctionTool] = []
    names: set[str] = set()

    for definition in surface.tools:
        handler = _make_handler(
            surface,
            ctx,
            step_index=step_index,
            definition=definition,
            on_tool_error=on_tool_error,
        )
        tools.append(
            FunctionTool(
                handler,
                description=definition.description or f"Invoke the {definition.name} tool.",
                name=definition.name,
            )
        )
        names.add(definition.name)

    return tools, frozenset(names)


def _make_handler(
    surface: AdapterToolSurface,
    ctx: AdapterContext,
    *,
    step_index: int,
    definition: ToolDefinition,
    on_tool_error: Callable[[str], None] | None = None,
):
    properties = (definition.parameters or {}).get("properties") or {}

    async def _execute(arguments: dict[str, Any]) -> str:
        try:
            result = await surface.execute(
                ctx,
                step_index=step_index,
                name=definition.name,
                arguments=arguments,
            )
            return _stringify_result(result)
        except Exception as exc:
            if on_tool_error is not None:
                on_tool_error(str(exc) or type(exc).__name__)
            return str(exc) or type(exc).__name__

    if not properties:
        async def handler() -> str:
            return await _execute({})

        handler.__name__ = definition.name
        return handler

    if set(properties) == {"text"}:
        async def handler(text: Annotated[str, "Tool input text."] = "") -> str:
            return await _execute({"text": text})

        handler.__name__ = definition.name
        return handler

    async def handler(input_json: Annotated[str, "JSON-encoded tool arguments."] = "{}") -> str:
        try:
            parsed = json.loads(input_json or "{}")
        except json.JSONDecodeError:
            parsed = {"raw": input_json}
        arguments = parsed if isinstance(parsed, dict) else {"value": parsed}
        return await _execute(arguments)

    handler.__name__ = definition.name
    return handler


def _stringify_result(result: dict[str, Any]) -> str:
    if not result:
        return ""
    if len(result) == 1 and "result" in result:
        value = result["result"]
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def inject_tools(runnable: Any, extra_tools: list[FunctionTool]) -> Any:
    """Attach bridged tools to an AutoGen agent when possible."""
    if not extra_tools:
        return runnable

    tools_attr = getattr(runnable, "_tools", None)
    if isinstance(tools_attr, list):
        existing_names = {getattr(tool, "name", None) for tool in tools_attr}
        for tool in extra_tools:
            if tool.name not in existing_names:
                tools_attr.append(tool)
        return runnable

    return runnable
