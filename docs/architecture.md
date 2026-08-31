# Architecture

AgentFlow is intentionally small. Every concept maps to a single file or a
small package so contributors can read the whole runtime in an afternoon.

## Runtime topology

The HTTP API and agent execution are separate processes. The Java API server
accepts REST/SSE traffic, enqueues run jobs to Redis, and relays live events.
One or more Python worker processes consume jobs, run orchestrator adapters,
and persist state to Postgres.

```
┌──────────────────────────────────────────────────────────────┐
│ Frontend (Next.js)                                           │
│   app/page.tsx          quick launch + agent list             │
│   app/runs/page.tsx     run list (polling)                    │
│   app/runs/[id]/page.tsx run detail + steps + SSE stream      │
└───────────────────┬──────────────────────────────────────────┘
                    │  REST + SSE
                    ▼
┌──────────────────────────────────────────────────────────────┐
│ API (Java / Spring Boot)                                     │
│   controller/AgentsController   CRUD agents                   │
│   controller/RunsController       create / get / cancel runs  │
│   controller/EventsController     SSE per-run event stream      │
│   jobs/JobProducer                XADD run jobs to Redis      │
│   jobs/CancelSignal               SET cancel keys               │
└───────────────────┬──────────────────────────────────────────┘
                    │  Redis Streams (jobs) + pub/sub (events)
                    ▼
┌──────────────────────────────────────────────────────────────┐
│ Worker (Python asyncio)                                      │
│   worker/runner.py            consume jobs, invoke executor   │
│   worker/queue.py             XREADGROUP / XACK / DLQ         │
└───────────────────┬──────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────┐    ┌──────────────────────────────┐
│ Adapters               │    │ Event bus                    │
│   adapters/base.py     │    │   events/bus.py              │
│   adapters/echo.py     │    │     - redis pub/sub (live)   │
│   adapters/langgraph.py│    │     - redis stream (replay)  │
└────────────────────────┘    │     - in-memory (unit tests) │
                              └──────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────────┐
│ Persistence (Postgres 16, Alembic-owned schema)              │
│   models/agent.py       Agent                                 │
│   models/run.py         Run, Step, Message, ToolCall, Checkpoint│
└──────────────────────────────────────────────────────────────┘
```

See [deployment.md](deployment.md) for the runbook and
[api-contract.md](api-contract.md) for the frozen `/v1` HTTP contract and the
API↔worker Redis protocol.

## Request → run lifecycle

1. Client `POST /v1/runs` with `agent_id` and `input`.
2. The Java API writes a `Run(status=pending)` row and enqueues a `RunJob`
   JSON payload on the Redis stream (`agentflow:jobs:runs` by default).
3. A Python worker `XREADGROUP`s the job, opens its own DB session, and
   invokes the configured `OrchestratorAdapter` via `RunExecutor`.
4. The adapter emits lifecycle events via `AdapterContext.emit_*`. The worker
   writes each event to Postgres, appends durable frames to Redis Stream
   `agentflow:run:{run_id}:log`, and publishes live `RunEvent`s on channel
   `agentflow:run:{run_id}` (`token.delta` is live-only).
5. The Java SSE controller replays from the stream when clients send
   `Last-Event-ID`, then relays live pub/sub events on
   `GET /v1/events/{run_id}`.
6. When the adapter returns, the worker writes the terminal status. The API
   and console observe the same rows and events.

Cancel works symmetrically: `POST /v1/runs/{id}/cancel` sets a Redis key under
`agentflow:cancel:{run_id}`; the worker polls that key and aborts the adapter.

## Why per-task sessions?

SQLAlchemy async sessions are not safe for concurrent use. The HTTP request
that created a run must not share a session with the background adapter work.
`RunExecutor` opens a fresh `AsyncSession` for each job.

## Adding an adapter

Built-in adapters:

1. Subclass `OrchestratorAdapter` in `app/adapters/`.
2. Implement `async def run(self, ctx: AdapterContext) -> AdapterResult`.
3. Emit events through `ctx.emit_step_started`, `ctx.emit_message`, etc.
4. Register it in `app/adapters/__init__.py` via `register_adapter`.

`register_adapter` refuses to rebind a name that is already taken, and refuses
to register one adapter instance under two names — the runtime resolves a run
by name and then reads `adapter.name` back to dispatch it, so the two must
agree.

Third-party adapters can be distributed as separate Python packages. Expose a
zero-argument factory through the `agentflow.adapters` entry-point group:

```toml
[project.entry-points."agentflow.adapters"]
crewai = "agentflow_crewai:create_adapter"
```

```python
def create_adapter() -> OrchestratorAdapter:
    return CrewAIAdapter()
```

The entry-point name becomes the adapter name. Plugin packages must be
installed in the Python worker environment before it starts. Duplicate names,
load failures, and factories that do not return an `OrchestratorAdapter` stop
startup. Because loading a plugin imports third-party code that may register
adapters of its own, conflicts are only settled once every factory has run:
the discovered batch is registered atomically, so a failure leaves the registry
exactly as it was.

No changes are needed in the DB schema, the `/v1` contract, or the frontend.
Workers pick up new adapters through the shared Python adapter registry.

The repository's official PydanticAI integration follows this layout in
`integrations/pydantic-ai`. Its `pydantic-ai` entry point keeps PydanticAI and
provider dependencies optional. A trusted `agent_factory` supplies an existing
Agent, including its instructions, output validators, native tools, and MCP
toolsets. One PydanticAI run maps to one runtime step; token deltas, output,
provider usage/cost, and tool events are translated to standard adapter events.
The MVP does not rebuild Agents from JSON or implement checkpoint/resume.

The official AutoGen integration lives in `integrations/autogen` and registers
the `autogen` entry point. A trusted `agent_factory` or `team_factory` returns
an AutoGen AgentChat agent or team. Single-agent runs map to one step; team
runs can emit one step per agent turn. Token deltas, messages, native tool
events, and AgentFlow-managed tools (via `AdapterToolSurface`) are translated
to the same adapter contract.

## MCP tool bridge

MCP (Model Context Protocol) tools are wired through a shared bridge so every
adapter persists the same `ToolCall` rows and SSE events:

```
agent.config.mcp_servers
        │
        ▼
  McpSessionManager          stdio / SSE / Streamable HTTP
        │
        ▼
  resolve_run_tools()        registry keys: mcp/{server}/{tool}
        │
        ▼
  AdapterToolSurface         emit tool_call.started / tool_call.completed
        │
        ├── McpAdapter           direct tool invocation (no LLM)
        └── LangGraphAdapter     tool / agent graph nodes
```

Configure servers in `agent.config.mcp_servers` and reference tools by key
(`mcp/{server}/{tool}`) in `agent.config.tools`, or set
`mcp_auto_register: true` to expose every tool from configured servers.

**Built-in `mcp` adapter** — for runs that only call MCP tools:

```jsonc
{
  "adapter": "mcp",
  "config": {
    "mcp_servers": [{
      "name": "echo",
      "transport": "stdio",
      "command": "python",
      "args": ["path/to/mcp_server.py"]
    }],
    "steps": [
      {"tool": "mcp/echo/ping", "arguments": {"message": "hello"}}
    ]
  }
}
```

Alternatively pass a single call or batch in run `input`:

```json
{"tool": "mcp/echo/ping", "arguments": {"message": "hello"}}
```

```json
{"calls": [
  {"tool": "mcp/echo/ping", "arguments": {"message": "a"}},
  {"tool": "mcp/echo/add", "arguments": {"a": 1, "b": 2}}
]}
```

LangGraph graphs can invoke the same MCP tools via `type: "tool"` or
`type: "agent"` nodes without a separate adapter.

### ReAct tool failure recovery

LangGraph `agent` nodes support an optional `tool_error_policy` in agent
config:

| Policy | Behavior |
| --- | --- |
| `fail_fast` (default) | Any tool exception fails the step/run (unchanged) |
| `feedback` | Only explicit `RecoverableToolError` becomes a safe tool observation; fatal errors still fail-fast |

Recoverable failures include MCP `CallToolResult.is_error=true` (mapped to a
fixed public message) and custom tools that raise `RecoverableToolError`.
Programming errors, transport/session failures, and cancellation continue to
propagate. Raw errors are persisted on `ToolCall.error`; the model only sees
a structured observation without traceback, arguments, or raw MCP text.

Provider `tool_call_id` values pair assistant tool calls with `role=tool`
messages. AgentFlow lifecycle ULIDs pair `tool_call.started` /
`tool_call.completed` events with `ToolCall.id` rows — these identifiers are
not unified in v1.

Parallel tool calls use standard `asyncio.gather` semantics: recoverable
failures can coexist with successes in one round, but a fatal error in any
parallel call fails the step without cancelling siblings or rolling back side
effects. `tool_error_policy` is interpreted only by LangGraph `agent` nodes;
the direct `mcp` adapter and PydanticAI bridge remain fail-fast.

When `feedback` is enabled and recoverable observations exhaust
`max_tool_rounds` without a final model reply, the run fails with
`tool_recovery_exhausted: reached max_tool_rounds=N`.

## Unit tests

The Python test suite in `backend/tests/` exercises adapter and queue logic
with an in-process ASGI client and in-memory or fake Redis. That harness is
not part of the production topology.
