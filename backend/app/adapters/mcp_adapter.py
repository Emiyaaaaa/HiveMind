"""MCP tool adapter – direct MCP invocation without an LLM orchestrator.

Use this adapter when a run should call one or more MCP tools and persist
standard ``ToolCall`` rows, without LangGraph or another framework in the loop.

Expected agent.config shape::

    {
      "mcp_servers": [
        {
          "name": "echo",
          "transport": "stdio",
          "command": "python",
          "args": ["path/to/mcp_server.py"]
        }
      ],
      "tools": ["mcp/echo/ping"],   // optional whitelist
      "mcp_auto_register": false,
      "steps": [                    // optional fixed sequence
        {"tool": "mcp/echo/ping", "arguments": {"message": "hello"}}
      ]
    }

Run ``input`` when ``steps`` is omitted::

    {"tool": "mcp/echo/ping", "arguments": {"message": "hello"}}

Batch form::

    {
      "calls": [
        {"tool": "mcp/echo/ping", "arguments": {"message": "hello"}},
        {"tool": "mcp/echo/add", "arguments": {"a": 1, "b": 2}}
      ]
    }
"""

from __future__ import annotations

from typing import Any

from app.adapters.adapter_tools import open_tool_surface
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.adapters.mcp_client import is_mcp_tool_key
from app.core.logging import get_logger
from app.models.run import RunStatus

logger = get_logger("adapter.mcp")


def _parse_tool_calls(
    agent_config: dict[str, Any], run_input: dict[str, Any]
) -> list[dict[str, Any]]:
    """Resolve the tool call sequence from agent config or run input."""
    raw_steps = agent_config.get("steps")
    if raw_steps is not None:
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("agent.config.steps must be a non-empty list")
        return [_normalize_call(entry, index) for index, entry in enumerate(raw_steps)]

    raw_calls = run_input.get("calls")
    if raw_calls is not None:
        if not isinstance(raw_calls, list) or not raw_calls:
            raise ValueError("input.calls must be a non-empty list")
        return [_normalize_call(entry, index) for index, entry in enumerate(raw_calls)]

    if "tool" in run_input:
        return [_normalize_call(run_input, 0)]

    raise ValueError(
        "MCP adapter requires agent.config.steps or run input with "
        "'tool'/'arguments' or a non-empty 'calls' list"
    )


def _normalize_call(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"tool call at index {index} must be an object")
    tool = entry.get("tool")
    if not tool or not isinstance(tool, str):
        raise ValueError(f"tool call at index {index} requires a string 'tool'")
    arguments = entry.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError(f"tool call at index {index}: 'arguments' must be an object")
    return {"tool": tool, "arguments": arguments}


class McpAdapter(OrchestratorAdapter):
    """Invoke MCP tools directly and emit standard ToolCall lifecycle events."""

    name = "mcp"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        try:
            calls = _parse_tool_calls(ctx.agent_config, ctx.input)
        except ValueError as exc:
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))

        for call in calls:
            if not is_mcp_tool_key(call["tool"]):
                return AdapterResult(
                    status=RunStatus.FAILED,
                    error=(
                        f"MCP adapter only supports MCP tool keys "
                        f"(mcp/{{server}}/{{tool}}); got {call['tool']!r}"
                    ),
                )

        tool_keys = list({call["tool"] for call in calls})
        configured_keys = list(ctx.agent_config.get("tools") or [])
        resolve_keys = configured_keys or tool_keys

        try:
            async with open_tool_surface(ctx.agent_config, resolve_keys) as surface:
                results: list[dict[str, Any]] = []
                for index, call in enumerate(calls):
                    step_index = ctx.step_index_base + index
                    tool_name = call["tool"]
                    arguments = call["arguments"]
                    node = tool_name.rsplit("/", 1)[-1]

                    await ctx.emit_step_started(index=step_index, node=node)
                    try:
                        result = await surface.execute(
                            ctx,
                            step_index=step_index,
                            name=tool_name,
                            arguments=arguments,
                        )
                    except Exception as exc:
                        await ctx.emit_step_failed(
                            index=step_index,
                            node=node,
                            error=str(exc),
                        )
                        return AdapterResult(
                            status=RunStatus.FAILED,
                            error=str(exc),
                        )

                    results.append(
                        {"tool": tool_name, "arguments": arguments, "result": result}
                    )
                    await ctx.emit_step_completed(
                        index=step_index,
                        node=node,
                        output={"tool": tool_name, "result": result},
                    )
                    logger.info(
                        "mcp_tool.completed",
                        tool=tool_name,
                        step_index=step_index,
                    )

                output = (
                    results[0]
                    if len(results) == 1
                    else {"calls": results, "count": len(results)}
                )
                return AdapterResult(status=RunStatus.SUCCEEDED, output=output)
        except KeyError as exc:
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))
        except RuntimeError as exc:
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))
