"""LangGraph adapter – the default production adapter.

The adapter constructs a ``StateGraph`` from the agent's config and streams
every node tick back to the runtime through ``AdapterContext``. LangGraph is
imported lazily so the rest of AgentFlow does not pay the import cost in tests
that exercise only the echo adapter.

Expected agent.config shape (all optional except when using custom graphs):

```jsonc
{
  "model": "openai/gpt-4o-mini",
  "system_prompt": "You are a helpful coordinator.",
  "stream_tokens": true,       // emit token.delta SSE; defer tokens to step.updated
  "tools": ["echo"],           // tool registry keys
  "graph": {
    "nodes": [
      {"id": "plan", "type": "model"},
      {"id": "tool", "type": "tool", "tool": "echo"},
      {"id": "reply", "type": "model", "system_prompt": "Summarize briefly."}
    ],
    "edges": [
      {"from": "__start__", "to": "plan"},
      {"from": "plan", "to": "tool"},
      {"from": "tool", "to": "reply"},
      {"from": "reply", "to": "__end__"}
    ]
  }
}
```

When ``graph`` is omitted a single-node ``call_model`` graph is used (backward
compatible with the MVP). Edge endpoints ``__start__`` / ``__end__`` map to
LangGraph ``START`` / ``END``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.adapters.tool_registry import ToolDefinition, resolve_tools, tool_schemas
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.run import RunStatus

logger = get_logger("adapter.langgraph")

START_NODE = "__start__"
END_NODE = "__end__"


@dataclass
class GraphNodeSpec:
    id: str
    type: str = "model"
    tool: str | None = None
    system_prompt: str | None = None
    model: str | None = None


@dataclass
class GraphEdgeSpec:
    from_node: str
    to: str


@dataclass
class GraphSpec:
    nodes: list[GraphNodeSpec]
    edges: list[GraphEdgeSpec]

    @classmethod
    def default(cls) -> GraphSpec:
        return cls(
            nodes=[GraphNodeSpec(id="call_model", type="model")],
            edges=[
                GraphEdgeSpec(from_node=START_NODE, to="call_model"),
                GraphEdgeSpec(from_node="call_model", to=END_NODE),
            ],
        )

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> GraphSpec:
        if not raw:
            return cls.default()
        nodes = [_parse_node(node) for node in raw.get("nodes", [])]
        edges = [_parse_edge(edge) for edge in raw.get("edges", [])]
        if not nodes:
            return cls.default()
        if not edges:
            edges = _linear_edges(nodes)
        return cls(nodes=nodes, edges=edges)


def _parse_node(raw: dict[str, Any] | str) -> GraphNodeSpec:
    if isinstance(raw, str):
        return GraphNodeSpec(id=raw, type="model")
    node_id = raw.get("id") or raw.get("name")
    if not node_id:
        raise ValueError("graph node requires 'id' or 'name'")
    return GraphNodeSpec(
        id=str(node_id),
        type=str(raw.get("type", "model")),
        tool=raw.get("tool"),
        system_prompt=raw.get("system_prompt"),
        model=raw.get("model"),
    )


def _parse_edge(raw: dict[str, Any] | list[str]) -> GraphEdgeSpec:
    if isinstance(raw, list):
        if len(raw) != 2:
            raise ValueError("edge list must be [from, to]")
        return GraphEdgeSpec(from_node=str(raw[0]), to=str(raw[1]))
    from_node = raw.get("from") or raw.get("source")
    to_node = raw.get("to") or raw.get("target")
    if not from_node or not to_node:
        raise ValueError("graph edge requires 'from' and 'to'")
    return GraphEdgeSpec(from_node=str(from_node), to=str(to_node))


def _linear_edges(nodes: list[GraphNodeSpec]) -> list[GraphEdgeSpec]:
    """Build START -> n0 -> ... -> END when edges are omitted."""
    edges = [GraphEdgeSpec(from_node=START_NODE, to=nodes[0].id)]
    for left, right in zip(nodes, nodes[1:], strict=False):
        edges.append(GraphEdgeSpec(from_node=left.id, to=right.id))
    edges.append(GraphEdgeSpec(from_node=nodes[-1].id, to=END_NODE))
    return edges


@dataclass
class _RunState:
    """Mutable per-run bookkeeping shared across graph nodes."""

    ctx: AdapterContext
    config: dict[str, Any]
    tools: list[ToolDefinition]
    default_model: str
    default_system_prompt: str
    step_index: int = 0
    node_indices: dict[str, int] = field(default_factory=dict)

    def next_step_index(self, node_id: str) -> int:
        if node_id not in self.node_indices:
            self.node_indices[node_id] = self.step_index
            self.step_index += 1
        return self.node_indices[node_id]


class LangGraphAdapter(OrchestratorAdapter):
    name = "langgraph"

    async def run(self, ctx: AdapterContext) -> AdapterResult:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError:  # pragma: no cover - dep guard
            return AdapterResult(
                status=RunStatus.FAILED,
                error="langgraph is not installed; add it to your environment.",
            )

        config = ctx.agent_config
        tool_keys: list[str] = list(config.get("tools") or [])
        try:
            tools = resolve_tools(tool_keys) if tool_keys else []
        except KeyError as exc:
            message = exc.args[0] if exc.args else str(exc)
            return AdapterResult(status=RunStatus.FAILED, error=str(message))

        try:
            graph_spec = GraphSpec.from_config(config.get("graph"))
        except ValueError as exc:
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))

        run_state = _RunState(
            ctx=ctx,
            config=config,
            tools=tools,
            default_model=str(config.get("model", "openai/gpt-4o-mini")),
            default_system_prompt=str(
                config.get("system_prompt", "You are a helpful agent.")
            ),
        )

        graph = StateGraph(dict)
        for node_spec in graph_spec.nodes:
            handler = self._make_node_handler(run_state, node_spec)
            graph.add_node(node_spec.id, handler)

        for edge in graph_spec.edges:
            src = START if edge.from_node == START_NODE else edge.from_node
            dst = END if edge.to == END_NODE else edge.to
            graph.add_edge(src, dst)

        compiled = graph.compile()
        initial = {
            "input": ctx.input.get("prompt", ""),
            "messages": [],
            "reply": None,
            "tool_results": {},
        }

        try:
            final_state = await compiled.ainvoke(initial)
        except Exception as exc:  # pragma: no cover - depends on external model
            logger.exception("langgraph_run_failed", run_id=ctx.run_id)
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))

        return AdapterResult(
            status=RunStatus.SUCCEEDED,
            output={"reply": final_state.get("reply")},
        )

    def _make_node_handler(
        self, run_state: _RunState, spec: GraphNodeSpec
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        if spec.type == "tool":
            return self._tool_node(run_state, spec)
        return self._model_node(run_state, spec)

    def _tool_node(
        self, run_state: _RunState, spec: GraphNodeSpec
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        tool_name = spec.tool
        if not tool_name and run_state.tools:
            tool_name = run_state.tools[0].name
        if not tool_name:
            raise ValueError(f"tool node {spec.id!r} has no tool configured")

        tool_def = next(
            (t for t in run_state.tools if t.name == tool_name),
            None,
        )
        if tool_def is None:
            from app.adapters.tool_registry import get_tool

            tool_def = get_tool(tool_name)

        async def handler(state: dict[str, Any]) -> dict[str, Any]:
            step_idx = run_state.next_step_index(spec.id)
            ctx = run_state.ctx
            arguments = {
                "text": state.get("reply") or state.get("input", ""),
                "input": state.get("input", ""),
            }
            await ctx.emit_step_started(index=step_idx, node=spec.id)
            await ctx.emit_tool_call_started(
                step_index=step_idx, name=tool_def.name, arguments=arguments
            )
            try:
                result = await tool_def.handler(arguments)
                if not isinstance(result, dict):
                    result = {"result": result}
                await ctx.emit_tool_call_completed(
                    step_index=step_idx, name=tool_def.name, result=result
                )
                await ctx.emit_step_completed(
                    index=step_idx,
                    node=spec.id,
                    output={"tool": tool_def.name, "result": result},
                )
                tool_results = dict(state.get("tool_results") or {})
                tool_results[tool_def.name] = result
                return {"tool_results": tool_results, "reply": str(result)}
            except Exception as exc:
                await ctx.emit_tool_call_completed(
                    step_index=step_idx,
                    name=tool_def.name,
                    error=str(exc),
                )
                await ctx.emit_step_failed(
                    index=step_idx, node=spec.id, error=str(exc)
                )
                raise

        return handler

    def _model_node(
        self, run_state: _RunState, spec: GraphNodeSpec
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        system_prompt = spec.system_prompt or run_state.default_system_prompt
        model = spec.model or run_state.default_model
        tool_keys: list[str] = list(run_state.config.get("tools") or [])

        async def handler(state: dict[str, Any]) -> dict[str, Any]:
            step_idx = run_state.next_step_index(spec.id)
            ctx = run_state.ctx
            user_input = str(state.get("input", ""))
            context_bits: list[str] = []
            if state.get("tool_results"):
                context_bits.append(f"tool_results={state['tool_results']!r}")
            if state.get("reply") and spec.id != "call_model":
                context_bits.append(f"prior_reply={state['reply']!r}")
            if context_bits:
                user_input = f"{user_input}\n\n" + "\n".join(context_bits)

            await ctx.emit_step_started(index=step_idx, node=spec.id)
            await ctx.emit_message(role="system", content=system_prompt)
            await ctx.emit_message(role="user", content=user_input)

            stream_tokens = run_state.config.get("stream_tokens", True)
            started = time.monotonic()
            reply, tokens_in, tokens_out = await self._invoke_model(
                ctx,
                step_idx,
                model,
                system_prompt,
                user_input,
                tool_keys=tool_keys if tool_keys else None,
                stream_tokens=bool(stream_tokens),
            )
            latency_ms = int((time.monotonic() - started) * 1000)

            await ctx.emit_step_updated(
                index=step_idx,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
            )
            await ctx.emit_message(role="assistant", content=reply)
            await ctx.emit_step_completed(
                index=step_idx,
                node=spec.id,
                output={"reply": reply},
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
            )
            messages = list(state.get("messages") or [])
            messages.extend(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": reply},
                ]
            )
            return {"reply": reply, "messages": messages}

        return handler

    async def _invoke_model(
        self,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        system_prompt: str,
        user_input: str,
        *,
        tool_keys: list[str] | None = None,
        stream_tokens: bool = True,
    ) -> tuple[str, int, int]:
        """Call the configured chat model, optionally streaming token deltas.

        Returns ``(reply, tokens_in, tokens_out)``. Token counts are taken from
        provider usage when available; otherwise estimated from text length.
        """
        settings = get_settings()
        if not settings.openai_api_key:
            return await self._invoke_mock(
                ctx,
                step_index,
                model,
                system_prompt,
                user_input,
                tool_keys=tool_keys,
                stream_tokens=stream_tokens,
            )

        import httpx

        payload: dict[str, Any] = {
            "model": model.split("/", 1)[-1],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
        }
        if tool_keys:
            payload["tools"] = tool_schemas(tool_keys)

        if stream_tokens and not tool_keys:
            return await self._invoke_openai_streaming(
                ctx, step_index, settings, payload
            )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls")
            if tool_calls:
                names = [tc["function"]["name"] for tc in tool_calls]
                reply = f"[tool_calls:{','.join(names)}]"
            else:
                reply = message.get("content") or ""
            usage = data.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or _estimate_tokens(system_prompt + user_input))
            tokens_out = int(usage.get("completion_tokens") or _estimate_tokens(reply))
            return reply, tokens_in, tokens_out

    async def _invoke_mock(
        self,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        system_prompt: str,
        user_input: str,
        *,
        tool_keys: list[str] | None = None,
        stream_tokens: bool = True,
    ) -> tuple[str, int, int]:
        suffix = ""
        if tool_keys:
            suffix = f" [tools={','.join(tool_keys)}]"
        reply = f"[mock:{model}]{suffix} {user_input}"
        tokens_in = _estimate_tokens(system_prompt + user_input)
        tokens_out = _estimate_tokens(reply)
        if stream_tokens:
            for chunk in _chunk_text(reply):
                await ctx.emit_token_delta(step_index=step_index, delta=chunk)
        return reply, tokens_in, tokens_out

    async def _invoke_openai_streaming(
        self,
        ctx: AdapterContext,
        step_index: int,
        settings: Any,
        payload: dict[str, Any],
    ) -> tuple[str, int, int]:
        import httpx

        payload = {
            **payload,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        parts: list[str] = []
        tokens_in = 0
        tokens_out = 0

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    usage = chunk.get("usage")
                    if usage:
                        tokens_in = int(usage.get("prompt_tokens") or tokens_in)
                        tokens_out = int(
                            usage.get("completion_tokens") or tokens_out
                        )
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            parts.append(content)
                            await ctx.emit_token_delta(
                                step_index=step_index, delta=content
                            )

        reply = "".join(parts)
        if not tokens_in:
            tokens_in = _estimate_tokens(
                str(payload.get("messages", ""))
            )
        if not tokens_out:
            tokens_out = _estimate_tokens(reply)
        return reply, tokens_in, tokens_out


def _estimate_tokens(text: str) -> int:
    """Rough token estimate when the provider omits usage (≈4 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _chunk_text(text: str, *, size: int = 8) -> list[str]:
    """Split text into small chunks for mock streaming."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]
