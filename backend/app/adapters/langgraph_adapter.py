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
  "tools": ["echo"],           // builtin or MCP keys (mcp/{server}/{tool})
  "mcp_servers": [             // optional MCP stdio/SSE/HTTP servers
    {
      "name": "echo",
      "transport": "stdio",
      "command": "python",
      "args": ["path/to/mcp_server.py"]
    }
  ],
  "mcp_auto_register": false,  // register every tool from mcp_servers
  "max_tool_rounds": 4,        // agent-node ReAct iterations (default 4)
  "graph": {
    "nodes": [
      {"id": "agent", "type": "agent"},
      {"id": "approve", "type": "human", "prompt": "Approve the draft?"},
      {"id": "reply", "type": "model", "system_prompt": "Summarize briefly."}
    ],
    "edges": [
      {"from": "__start__", "to": "agent"},
      {"from": "agent", "to": "approve"},
      {
        "from": "approve",
        "condition": "route",
        "routes": {"approved": "reply", "rejected": "__end__"},
        "default": "reply"
      },
      {"from": "reply", "to": "__end__"}
    ]
  }
}
```

Node types:
- ``model`` – single LLM call (optional tool schemas; does not execute tools)
- ``tool`` – invoke one configured tool via ``AdapterToolSurface`` (builtin/MCP)
- ``agent`` – ReAct loop: model ↔ tools until a final reply or ``max_tool_rounds``
- ``human`` – pause as ``waiting_human``; resume merges ``human_input`` and continues

When ``graph`` is omitted a single-node ``call_model`` graph is used (backward
compatible with the MVP). Edge endpoints ``__start__`` / ``__end__`` map to
LangGraph ``START`` / ``END``. Conditional edges use ``condition`` + ``routes``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.adapters.adapter_tools import (
    AdapterToolSurface,
    build_tool_arguments,
    tool_schemas_from_definitions,
)
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.adapters.tool_registry import ToolDefinition
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.run import RunStatus
from app.runtime.pricing import estimate_cost_usd
from app.runtime.tokens import estimate_tokens

logger = get_logger("adapter.langgraph")

START_NODE = "__start__"
END_NODE = "__end__"
DEFAULT_MAX_TOOL_ROUNDS = 4


class WaitingHumanInterrupt(Exception):
    """Raised by a ``human`` node to pause the run for approval."""

    def __init__(self, output: dict[str, Any]) -> None:
        super().__init__(output.get("awaiting", "waiting for human"))
        self.output = output


@dataclass
class ModelResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class GraphNodeSpec:
    id: str
    type: str = "model"
    tool: str | None = None
    system_prompt: str | None = None
    model: str | None = None
    max_iterations: int | None = None
    prompt: str | None = None


@dataclass
class GraphEdgeSpec:
    from_node: str
    to: str | None = None
    condition_key: str | None = None
    routes: dict[str, str] | None = None
    default: str | None = None

    @property
    def is_conditional(self) -> bool:
        return bool(self.routes)


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
    node_type = str(raw.get("type", "model"))
    if node_type not in ("model", "tool", "agent", "human"):
        raise ValueError(
            f"unsupported graph node type {node_type!r}; "
            "expected model|tool|agent|human"
        )
    max_iterations = raw.get("max_iterations")
    if max_iterations is not None:
        max_iterations = int(max_iterations)
    return GraphNodeSpec(
        id=str(node_id),
        type=node_type,
        tool=raw.get("tool"),
        system_prompt=raw.get("system_prompt"),
        model=raw.get("model"),
        max_iterations=max_iterations,
        prompt=raw.get("prompt"),
    )


def _parse_edge(raw: dict[str, Any] | list[str]) -> GraphEdgeSpec:
    if isinstance(raw, list):
        if len(raw) != 2:
            raise ValueError("edge list must be [from, to]")
        return GraphEdgeSpec(from_node=str(raw[0]), to=str(raw[1]))

    from_node = raw.get("from") or raw.get("source")
    if not from_node:
        raise ValueError("graph edge requires 'from'")

    routes = raw.get("routes") or raw.get("path_map")
    if routes is not None:
        if not isinstance(routes, dict) or not routes:
            raise ValueError("conditional edge 'routes' must be a non-empty object")
        condition_key = raw.get("condition") or raw.get("key") or "route"
        return GraphEdgeSpec(
            from_node=str(from_node),
            condition_key=str(condition_key),
            routes={str(k): str(v) for k, v in routes.items()},
            default=str(raw["default"]) if raw.get("default") is not None else None,
        )

    to_node = raw.get("to") or raw.get("target")
    if not to_node:
        raise ValueError("graph edge requires 'to' (or 'routes' for conditional)")
    return GraphEdgeSpec(from_node=str(from_node), to=str(to_node))


def _linear_edges(nodes: list[GraphNodeSpec]) -> list[GraphEdgeSpec]:
    """Build START -> n0 -> ... -> END when edges are omitted."""
    edges = [GraphEdgeSpec(from_node=START_NODE, to=nodes[0].id)]
    for left, right in zip(nodes, nodes[1:], strict=False):
        edges.append(GraphEdgeSpec(from_node=left.id, to=right.id))
    edges.append(GraphEdgeSpec(from_node=nodes[-1].id, to=END_NODE))
    return edges


def _map_endpoint(node_id: str, *, start: Any, end: Any) -> Any:
    if node_id == START_NODE:
        return start
    if node_id == END_NODE:
        return end
    return node_id


@dataclass
class _RunState:
    """Mutable per-run bookkeeping shared across graph nodes."""

    ctx: AdapterContext
    config: dict[str, Any]
    tools: list[ToolDefinition]
    tool_surface: AdapterToolSurface
    default_model: str
    default_system_prompt: str
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    step_index: int = 0
    node_indices: dict[str, int] = field(default_factory=dict)

    def next_step_index(self, node_id: str) -> int:
        if node_id not in self.node_indices:
            self.node_indices[node_id] = self.ctx.step_index_base + self.step_index
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
            tool_surface = await AdapterToolSurface.open(config, tool_keys)
        except KeyError as exc:
            message = exc.args[0] if exc.args else str(exc)
            return AdapterResult(status=RunStatus.FAILED, error=str(message))

        try:
            graph_spec = GraphSpec.from_config(config.get("graph"))
        except ValueError as exc:
            await tool_surface.close()
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))

        max_rounds = int(config.get("max_tool_rounds", DEFAULT_MAX_TOOL_ROUNDS))
        run_state = _RunState(
            ctx=ctx,
            config=config,
            tools=tool_surface.tools,
            tool_surface=tool_surface,
            default_model=str(config.get("model", "openai/gpt-4o-mini")),
            default_system_prompt=str(
                config.get("system_prompt", "You are a helpful agent.")
            ),
            max_tool_rounds=max(1, max_rounds),
        )

        graph = StateGraph(dict)
        for node_spec in graph_spec.nodes:
            handler = self._make_node_handler(run_state, node_spec)
            graph.add_node(node_spec.id, handler)

        try:
            self._wire_edges(graph, graph_spec.edges, start=START, end=END)
        except ValueError as exc:
            await tool_surface.close()
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))

        compiled = graph.compile()
        initial = _initial_graph_state(ctx)
        if ctx.resume and ctx.resume.mode == "resume" and ctx.resume.human_input:
            initial = {
                **initial,
                "human_input": ctx.resume.human_input,
                "route": str(
                    ctx.resume.human_input.get(
                        "route", initial.get("route") or "approved"
                    )
                ),
            }

        try:
            final_state = await compiled.ainvoke(initial)
        except WaitingHumanInterrupt as pending:
            return AdapterResult(
                status=RunStatus.WAITING_HUMAN,
                output=pending.output,
            )
        except Exception as exc:  # pragma: no cover - depends on external model
            logger.exception("langgraph_run_failed", run_id=ctx.run_id)
            return AdapterResult(status=RunStatus.FAILED, error=str(exc))
        finally:
            await tool_surface.close()

        return AdapterResult(
            status=RunStatus.SUCCEEDED,
            output={"reply": final_state.get("reply")},
        )

    def _wire_edges(
        self,
        graph: Any,
        edges: list[GraphEdgeSpec],
        *,
        start: Any,
        end: Any,
    ) -> None:
        for edge in edges:
            src = _map_endpoint(edge.from_node, start=start, end=end)
            if edge.is_conditional:
                assert edge.routes is not None
                path_map = {
                    key: _map_endpoint(dest, start=start, end=end)
                    for key, dest in edge.routes.items()
                }
                condition_key = edge.condition_key or "route"
                default_key = edge.default
                if default_key is not None and default_key not in path_map:
                    # ``default`` may be a route key (already in path_map) or a
                    # destination node id / __end__ — register it under a sentinel.
                    path_map["__default__"] = _map_endpoint(
                        default_key, start=start, end=end
                    )
                    default_key = "__default__"

                def _router(
                    state: dict[str, Any],
                    *,
                    _key: str = condition_key,
                    _routes: dict[str, Any] = path_map,
                    _default: str | None = default_key,
                ) -> str:
                    value = state.get(_key)
                    if value is not None and str(value) in _routes:
                        return str(value)
                    if _default is not None and _default in _routes:
                        return _default
                    return next(iter(_routes))

                graph.add_conditional_edges(src, _router, path_map)
            else:
                if not edge.to:
                    raise ValueError(
                        f"edge from {edge.from_node!r} is missing 'to'"
                    )
                dst = _map_endpoint(edge.to, start=start, end=end)
                graph.add_edge(src, dst)

    def _make_node_handler(
        self, run_state: _RunState, spec: GraphNodeSpec
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        if spec.type == "tool":
            return self._tool_node(run_state, spec)
        if spec.type == "agent":
            return self._agent_node(run_state, spec)
        if spec.type == "human":
            return self._human_node(run_state, spec)
        return self._model_node(run_state, spec)

    def _tool_node(
        self, run_state: _RunState, spec: GraphNodeSpec
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        tool_name = spec.tool
        if not tool_name and run_state.tools:
            tool_name = run_state.tools[0].name
        if not tool_name:
            raise ValueError(f"tool node {spec.id!r} has no tool configured")

        tool_def = run_state.tool_surface.lookup(tool_name)

        async def handler(state: dict[str, Any]) -> dict[str, Any]:
            if _already_completed(state, spec.id):
                return {}
            step_idx = run_state.next_step_index(spec.id)
            ctx = run_state.ctx
            arguments = build_tool_arguments(tool_def, state)
            await ctx.emit_step_started(index=step_idx, node=spec.id)
            try:
                result = await run_state.tool_surface.execute(
                    ctx,
                    step_index=step_idx,
                    name=tool_def.name,
                    arguments=arguments,
                )
                await ctx.emit_step_completed(
                    index=step_idx,
                    node=spec.id,
                    output={"tool": tool_def.name, "result": result},
                )
                tool_results = dict(state.get("tool_results") or {})
                tool_results[tool_def.name] = result
                next_state = {
                    "tool_results": tool_results,
                    "reply": str(result),
                    "completed_nodes": _with_completed(state, spec.id),
                }
                await ctx.emit_checkpoint(
                    label=spec.id,
                    state={"graph_state": {**state, **next_state}},
                )
                return next_state
            except Exception as exc:
                await ctx.emit_step_failed(
                    index=step_idx, node=spec.id, error=str(exc)
                )
                raise

        return handler

    def _human_node(
        self, run_state: _RunState, spec: GraphNodeSpec
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        async def handler(state: dict[str, Any]) -> dict[str, Any]:
            if _already_completed(state, spec.id):
                return {}

            ctx = run_state.ctx
            pending = state.get("pending_human")
            resuming = (
                ctx.resume is not None
                and ctx.resume.mode == "resume"
                and pending == spec.id
            )

            if resuming:
                step_idx = run_state.next_step_index(spec.id)
                human_input = dict(ctx.resume.human_input or {})  # type: ignore[union-attr]
                await ctx.emit_step_started(index=step_idx, node=spec.id)
                route = str(human_input.get("route") or state.get("route") or "approved")
                next_state = {
                    "human_input": human_input,
                    "route": route,
                    "pending_human": None,
                    "completed_nodes": _with_completed(state, spec.id),
                }
                await ctx.emit_step_completed(
                    index=step_idx,
                    node=spec.id,
                    output={"human_input": human_input, "route": route},
                )
                await ctx.emit_checkpoint(
                    label=spec.id,
                    state={"graph_state": {**state, **next_state}},
                )
                return next_state

            awaiting = spec.prompt or f"Human approval required at node {spec.id}"
            pause_state = {
                **state,
                "pending_human": spec.id,
                "completed_nodes": list(state.get("completed_nodes") or []),
            }
            await ctx.emit_checkpoint(
                label=spec.id,
                state={"graph_state": pause_state},
            )
            raise WaitingHumanInterrupt(
                output={
                    "awaiting": awaiting,
                    "node": spec.id,
                    "reply": state.get("reply"),
                }
            )

        return handler

    def _agent_node(
        self, run_state: _RunState, spec: GraphNodeSpec
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        system_prompt = spec.system_prompt or run_state.default_system_prompt
        model = spec.model or run_state.default_model
        max_rounds = spec.max_iterations or run_state.max_tool_rounds
        resolved_tools = run_state.tools

        async def handler(state: dict[str, Any]) -> dict[str, Any]:
            if _already_completed(state, spec.id):
                return {}

            step_idx = run_state.next_step_index(spec.id)
            ctx = run_state.ctx
            stream_tokens = run_state.config.get("stream_tokens", True)
            messages = _seed_agent_messages(state, system_prompt)
            tool_results = dict(state.get("tool_results") or {})
            started = time.monotonic()
            total_in = 0
            total_out = 0
            final_reply = ""

            await ctx.emit_step_started(index=step_idx, node=spec.id)
            await ctx.emit_message(role="system", content=system_prompt)
            user_seed = str(state.get("input", ""))
            if user_seed:
                await ctx.emit_message(role="user", content=user_seed)

            try:
                for round_idx in range(max_rounds):
                    response = await self._invoke_model(
                        ctx,
                        step_idx,
                        model,
                        messages,
                        tools=resolved_tools if resolved_tools else None,
                        stream_tokens=bool(stream_tokens) and not resolved_tools,
                        mock_tool_round=round_idx if resolved_tools else None,
                    )
                    total_in += response.tokens_in
                    total_out += response.tokens_out

                    if response.tool_calls:
                        messages.append(
                            {
                                "role": "assistant",
                                "content": response.content or None,
                                "tool_calls": [
                                    _openai_tool_call_payload(tc)
                                    for tc in response.tool_calls
                                ],
                            }
                        )
                        for tc in response.tool_calls:
                            name = str(tc.get("name") or "")
                            arguments = dict(tc.get("arguments") or {})
                            result = await run_state.tool_surface.execute(
                                ctx,
                                step_index=step_idx,
                                name=name,
                                arguments=arguments,
                            )
                            tool_results[name] = result
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": str(tc.get("id") or name),
                                    "content": json.dumps(result, default=str),
                                }
                            )
                        continue

                    final_reply = response.content or ""
                    messages.append({"role": "assistant", "content": final_reply})
                    break
                else:
                    final_reply = (
                        final_reply
                        or f"[agent:{spec.id}] reached max_tool_rounds={max_rounds}"
                    )
                    messages.append({"role": "assistant", "content": final_reply})

                latency_ms = int((time.monotonic() - started) * 1000)
                cost_usd = estimate_cost_usd(model, total_in, total_out)
                await ctx.emit_message(role="assistant", content=final_reply)
                await ctx.emit_step_updated(
                    index=step_idx,
                    tokens_in=total_in,
                    tokens_out=total_out,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                )
                await ctx.emit_step_completed(
                    index=step_idx,
                    node=spec.id,
                    output={"reply": final_reply, "tool_results": tool_results},
                    tokens_in=total_in,
                    tokens_out=total_out,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                )
                next_state = {
                    "reply": final_reply,
                    "messages": messages,
                    "tool_results": tool_results,
                    "completed_nodes": _with_completed(state, spec.id),
                }
                await ctx.emit_checkpoint(
                    label=spec.id,
                    state={"graph_state": {**state, **next_state}},
                )
                return next_state
            except WaitingHumanInterrupt:
                raise
            except Exception as exc:
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
        resolved_tools = run_state.tools

        async def handler(state: dict[str, Any]) -> dict[str, Any]:
            if _already_completed(state, spec.id):
                return {}

            step_idx = run_state.next_step_index(spec.id)
            ctx = run_state.ctx
            user_input = str(state.get("input", ""))
            context_bits: list[str] = []
            if state.get("tool_results"):
                context_bits.append(f"tool_results={state['tool_results']!r}")
            if state.get("human_input"):
                context_bits.append(f"human_input={state['human_input']!r}")
            if state.get("reply") and spec.id != "call_model":
                context_bits.append(f"prior_reply={state['reply']!r}")
            if context_bits:
                user_input = f"{user_input}\n\n" + "\n".join(context_bits)

            await ctx.emit_step_started(index=step_idx, node=spec.id)
            await ctx.emit_message(role="system", content=system_prompt)
            await ctx.emit_message(role="user", content=user_input)

            stream_tokens = run_state.config.get("stream_tokens", True)
            started = time.monotonic()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ]
            response = await self._invoke_model(
                ctx,
                step_idx,
                model,
                messages,
                tools=resolved_tools if resolved_tools else None,
                stream_tokens=bool(stream_tokens) and not resolved_tools,
            )
            if response.tool_calls:
                names = [str(tc.get("name") or "") for tc in response.tool_calls]
                reply = f"[tool_calls:{','.join(names)}]"
            else:
                reply = response.content
            latency_ms = int((time.monotonic() - started) * 1000)
            cost_usd = estimate_cost_usd(
                model, response.tokens_in, response.tokens_out
            )

            await ctx.emit_step_updated(
                index=step_idx,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
            await ctx.emit_message(role="assistant", content=reply)
            await ctx.emit_step_completed(
                index=step_idx,
                node=spec.id,
                output={"reply": reply},
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
            history = list(state.get("messages") or [])
            history.extend(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": reply},
                ]
            )
            next_state = {
                "reply": reply,
                "messages": history,
                "completed_nodes": _with_completed(state, spec.id),
            }
            await ctx.emit_checkpoint(
                label=spec.id,
                state={"graph_state": {**state, **next_state}},
            )
            return next_state

        return handler

    async def _invoke_model(
        self,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[ToolDefinition] | None = None,
        stream_tokens: bool = True,
        mock_tool_round: int | None = None,
    ) -> ModelResponse:
        """Call the configured chat model, optionally streaming token deltas."""
        settings = get_settings()
        if not settings.openai_api_key:
            return await self._invoke_mock(
                ctx,
                step_index,
                model,
                messages,
                tools=tools,
                stream_tokens=stream_tokens,
                mock_tool_round=mock_tool_round,
            )

        import httpx

        payload: dict[str, Any] = {
            "model": model.split("/", 1)[-1],
            "messages": messages,
        }
        if tools:
            payload["tools"] = tool_schemas_from_definitions(tools)

        if stream_tokens and not tools:
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
            tool_calls = _parse_openai_tool_calls(message.get("tool_calls"))
            content = message.get("content") or ""
            usage = data.get("usage") or {}
            prompt_text = json.dumps(messages, default=str)
            tokens_in = int(
                usage.get("prompt_tokens") or estimate_tokens(prompt_text)
            )
            tokens_out = int(
                usage.get("completion_tokens")
                or estimate_tokens(content or json.dumps(tool_calls, default=str))
            )
            return ModelResponse(
                content=content,
                tool_calls=tool_calls,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )

    async def _invoke_mock(
        self,
        ctx: AdapterContext,
        step_index: int,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[ToolDefinition] | None = None,
        stream_tokens: bool = True,
        mock_tool_round: int | None = None,
    ) -> ModelResponse:
        user_bits = [
            str(m.get("content") or "")
            for m in messages
            if m.get("role") == "user" and m.get("content")
        ]
        user_input = user_bits[-1] if user_bits else ""

        if tools and mock_tool_round == 0:
            tool = tools[0]
            arguments = build_tool_arguments(
                tool, {"input": user_input, "reply": user_input}
            )
            return ModelResponse(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{tool.name}",
                        "name": tool.name,
                        "arguments": arguments,
                    }
                ],
                tokens_in=estimate_tokens(user_input),
                tokens_out=estimate_tokens(tool.name),
            )

        suffix = ""
        if tools:
            suffix = f" [tools={','.join(t.name for t in tools)}]"
        # Prefer the latest tool result when summarizing after a tool round.
        tool_msgs = [
            m.get("content")
            for m in messages
            if m.get("role") == "tool" and m.get("content")
        ]
        if tool_msgs:
            reply = f"[mock:{model}]{suffix} tool_result={tool_msgs[-1]}"
        else:
            reply = f"[mock:{model}]{suffix} {user_input}"
        tokens_in = estimate_tokens(json.dumps(messages, default=str))
        tokens_out = estimate_tokens(reply)
        if stream_tokens:
            for chunk in _chunk_text(reply):
                await ctx.emit_token_delta(step_index=step_index, delta=chunk)
        return ModelResponse(
            content=reply,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    async def _invoke_openai_streaming(
        self,
        ctx: AdapterContext,
        step_index: int,
        settings: Any,
        payload: dict[str, Any],
    ) -> ModelResponse:
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
            tokens_in = estimate_tokens(str(payload.get("messages", "")))
        if not tokens_out:
            tokens_out = estimate_tokens(reply)
        return ModelResponse(
            content=reply, tokens_in=tokens_in, tokens_out=tokens_out
        )


def _already_completed(state: dict[str, Any], node_id: str) -> bool:
    completed = state.get("completed_nodes") or []
    return node_id in completed


def _with_completed(state: dict[str, Any], node_id: str) -> list[str]:
    completed = list(state.get("completed_nodes") or [])
    if node_id not in completed:
        completed.append(node_id)
    return completed


def _seed_agent_messages(
    state: dict[str, Any], system_prompt: str
) -> list[dict[str, Any]]:
    existing = state.get("messages")
    if isinstance(existing, list) and existing:
        return list(existing)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    user_input = str(state.get("input", ""))
    if user_input:
        messages.append({"role": "user", "content": user_input})
    return messages


def _parse_openai_tool_calls(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    parsed: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or {}
        arguments = fn.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        parsed.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(fn.get("name") or ""),
                "arguments": arguments,
            }
        )
    return parsed


def _openai_tool_call_payload(tc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(tc.get("id") or tc.get("name") or "call"),
        "type": "function",
        "function": {
            "name": str(tc.get("name") or ""),
            "arguments": json.dumps(tc.get("arguments") or {}),
        },
    }


def _initial_graph_state(ctx: AdapterContext) -> dict[str, Any]:
    default: dict[str, Any] = {
        "input": ctx.input.get("prompt", ""),
        "messages": [],
        "reply": None,
        "tool_results": {},
        "completed_nodes": [],
        "pending_human": None,
        "human_input": None,
        "route": None,
    }
    if ctx.resume and ctx.resume.checkpoint_state:
        saved = ctx.resume.checkpoint_state.get("graph_state")
        if isinstance(saved, dict):
            return {**default, **saved}
    return default


def _chunk_text(text: str, *, size: int = 8) -> list[str]:
    """Split text into small chunks for mock streaming."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]
