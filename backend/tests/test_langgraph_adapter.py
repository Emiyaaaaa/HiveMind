"""LangGraph adapter and tool registry tests (no live LLM)."""

from __future__ import annotations

from typing import Any

import pytest

from app.adapters.base import AdapterContext, AdapterResult
from app.adapters.langgraph_adapter import GraphSpec, LangGraphAdapter
from app.adapters.tool_registry import get_tool, list_tools, register_tool, resolve_tools
from app.models.run import RunStatus


class _RecordingContext(AdapterContext):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        super().__init__(
            run_id="01TEST",
            agent_id="01AGENT",
            agent_config={},
            input={"prompt": "hello"},
            emit=self._emit,
        )

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


@pytest.mark.asyncio
async def test_tool_registry_builtins():
    assert "echo" in list_tools()
    tool = get_tool("echo")
    result = await tool.handler({"text": "ping"})
    assert result == {"text": "ping"}


@pytest.mark.asyncio
async def test_tool_registry_custom():
    async def double(args: dict[str, Any]) -> dict[str, Any]:
        return {"value": int(args.get("n", 0)) * 2}

    register_tool("double", double, overwrite=True)
    assert resolve_tools(["double"])[0].name == "double"
    out = await get_tool("double").handler({"n": 3})
    assert out == {"value": 6}


def test_graph_spec_default():
    spec = GraphSpec.default()
    assert len(spec.nodes) == 1
    assert spec.nodes[0].id == "call_model"


def test_graph_spec_from_config_linear_fallback():
    spec = GraphSpec.from_config(
        {
            "nodes": [
                {"id": "plan", "type": "model"},
                {"id": "tool", "type": "tool", "tool": "echo"},
                {"id": "reply", "type": "model"},
            ],
        }
    )
    assert [n.id for n in spec.nodes] == ["plan", "tool", "reply"]
    assert spec.edges[0].from_node == "__start__"
    assert spec.edges[-1].to == "__end__"


@pytest.mark.asyncio
async def test_langgraph_default_single_node():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = {"model": "openai/gpt-4o-mini"}
    result = await adapter.run(ctx)
    assert result.status == RunStatus.SUCCEEDED
    assert result.output == {"reply": "[mock:openai/gpt-4o-mini] hello"}
    step_nodes = [
        data["node"]
        for event, data in ctx.events
        if event == "step.started"
    ]
    assert step_nodes == ["call_model"]


@pytest.mark.asyncio
async def test_langgraph_multi_node_with_tool():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = {
        "model": "openai/gpt-4o-mini",
        "system_prompt": "Be brief.",
        "tools": ["echo"],
        "graph": {
            "nodes": [
                {"id": "draft", "type": "model"},
                {"id": "echo_step", "type": "tool", "tool": "echo"},
                {"id": "finalize", "type": "model"},
            ],
            "edges": [
                ["__start__", "draft"],
                ["draft", "echo_step"],
                ["echo_step", "finalize"],
                ["finalize", "__end__"],
            ],
        },
    }
    result = await adapter.run(ctx)
    assert result.status == RunStatus.SUCCEEDED
    step_nodes = [
        data["node"]
        for event, data in ctx.events
        if event == "step.started"
    ]
    assert step_nodes == ["draft", "echo_step", "finalize"]
    tool_events = [e for e, _ in ctx.events if e.startswith("tool_call.")]
    assert len(tool_events) == 2


@pytest.mark.asyncio
async def test_langgraph_unknown_tool_fails():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = {"tools": ["does_not_exist"]}
    result = await adapter.run(ctx)
    assert result.status == RunStatus.FAILED
    assert "Unknown tool" in (result.error or "")


@pytest.mark.asyncio
async def test_langgraph_streams_token_deltas_and_defers_step_tokens():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = {"model": "openai/gpt-4o-mini", "stream_tokens": True}
    result = await adapter.run(ctx)
    assert result.status == RunStatus.SUCCEEDED

    token_events = [
        data for event, data in ctx.events if event == "token.delta"
    ]
    assert len(token_events) > 0
    assert all(e["step_index"] == 0 for e in token_events)
    reply = (result.output or {}).get("reply", "")
    assert "".join(e["delta"] for e in token_events) == reply

    updated = [
        data for event, data in ctx.events if event == "step.updated"
    ]
    assert len(updated) == 1
    assert updated[0]["tokens_in"] > 0
    assert updated[0]["tokens_out"] > 0
    assert updated[0]["latency_ms"] >= 0

    completed = [
        data
        for event, data in ctx.events
        if event == "step.completed" and data["node"] == "call_model"
    ]
    assert completed[0]["tokens_in"] == updated[0]["tokens_in"]
    assert completed[0]["tokens_out"] == updated[0]["tokens_out"]


@pytest.mark.asyncio
async def test_langgraph_stream_tokens_disabled():
    adapter = LangGraphAdapter()
    ctx = _RecordingContext()
    ctx.agent_config = {
        "model": "openai/gpt-4o-mini",
        "stream_tokens": False,
    }
    await adapter.run(ctx)
    assert not any(event == "token.delta" for event, _ in ctx.events)
