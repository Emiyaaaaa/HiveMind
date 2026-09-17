"""Bridge AgentFlow-managed tools into AutoGen ``FunctionTool`` instances."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from app.adapters.adapter_tools import AdapterToolSurface
from app.adapters.base import AdapterContext
from app.adapters.tool_registry import ToolDefinition
from autogen_core.tools import FunctionTool


@dataclass(frozen=True, slots=True)
class BridgedToolExecution:
    """A tool result waiting for AutoGen to reveal its owning turn."""

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    latency_ms: int


def build_function_tools(
    surface: AdapterToolSurface,
    ctx: AdapterContext,
    *,
    step_index: int | Callable[[], int],
    on_tool_error: Callable[[str], None] | None = None,
    on_tool_execution: Callable[[BridgedToolExecution], None] | None = None,
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
            on_tool_execution=on_tool_execution,
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
    step_index: int | Callable[[], int],
    definition: ToolDefinition,
    on_tool_error: Callable[[str], None] | None = None,
    on_tool_execution: Callable[[BridgedToolExecution], None] | None = None,
):
    properties = (definition.parameters or {}).get("properties") or {}

    async def _execute(arguments: dict[str, Any]) -> str:
        try:
            if on_tool_execution is None:
                current_step_index = step_index() if callable(step_index) else step_index
                result = await surface.execute(
                    ctx,
                    step_index=current_step_index,
                    name=definition.name,
                    arguments=arguments,
                )
            else:
                started = time.monotonic()
                try:
                    result = await surface.lookup(definition.name).handler(arguments)
                except Exception as exc:
                    error = str(exc) or type(exc).__name__
                    on_tool_execution(
                        BridgedToolExecution(
                            name=definition.name,
                            arguments=arguments,
                            result=None,
                            error=error,
                            latency_ms=int((time.monotonic() - started) * 1000),
                        )
                    )
                    raise
                if not isinstance(result, dict):
                    result = {"result": result}
                on_tool_execution(
                    BridgedToolExecution(
                        name=definition.name,
                        arguments=arguments,
                        result=result,
                        error=None,
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                )
            return _stringify_result(result)
        except Exception as exc:
            if on_tool_error is not None:
                on_tool_error(str(exc) or type(exc).__name__)
            return str(exc) or type(exc).__name__

    if not properties:
        async def no_arguments_handler() -> str:
            return await _execute({})

        no_arguments_handler.__name__ = definition.name
        return no_arguments_handler

    if set(properties) == {"text"}:
        async def text_handler(text: Annotated[str, "Tool input text."] = "") -> str:
            return await _execute({"text": text})

        text_handler.__name__ = definition.name
        return text_handler

    async def json_handler(input_json: Annotated[str, "JSON-encoded tool arguments."] = "{}") -> str:
        try:
            parsed = json.loads(input_json or "{}")
        except json.JSONDecodeError:
            parsed = {"raw": input_json}
        arguments = parsed if isinstance(parsed, dict) else {"value": parsed}
        return await _execute(arguments)

    json_handler.__name__ = definition.name
    return json_handler


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
