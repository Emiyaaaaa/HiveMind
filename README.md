# AgentFlow

> A Python-first runtime layer for multi-agent systems, with persistent run
> state, streaming execution events, and a pluggable orchestration interface.

[中文](README.zh-CN.md) · [Architecture](docs/architecture.md) · [Data model](docs/data-model.md)

[![CI](https://github.com/your-org/agentflow/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/agentflow/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org)

AgentFlow provides the runtime infrastructure around multi-agent applications.
It does not replace frameworks such as LangGraph, AutoGen or CrewAI. Instead,
it gives them a consistent execution model: agents are invoked as runs, runs
produce ordered steps and messages, tool calls are recorded, and every state
change can be streamed to a client.

The project is designed for teams that want to move from an agent prototype to
an inspectable service without committing to a single orchestration framework
or rebuilding persistence, event streaming and operational tooling for each
new agent.

> Status: early MVP. The current implementation defines the core shape of the
> runtime, but public APIs may still change before a stable release.

## Motivation

Agent frameworks are usually optimized for local composition: prompts, tools,
graphs, roles and model calls. Production systems need additional runtime
concerns that sit outside the framework itself:

- durable run history across process restarts;
- ordered step, message and tool-call records for debugging and audit;
- streaming events for web clients and SDK consumers;
- cancellation, retry and resume primitives;
- a stable abstraction for switching or mixing orchestration frameworks;
- an operator-facing console for inspecting active and historical runs.

AgentFlow focuses on that runtime boundary. The core service is intentionally
small: FastAPI for HTTP and SSE, SQLAlchemy for persistence, an event bus for
live updates, and an adapter interface for orchestration frameworks.

## Core capabilities

- **Orchestrator adapters.** The default adapter uses LangGraph. Additional
  adapters can be registered for AutoGen, CrewAI, PydanticAI or internal
  frameworks without changing the API or database schema.
- **Persistent execution model.** `Run`, `Step`, `Message`, `ToolCall` and
  `Checkpoint` are first-class database entities. They provide a common
  observability surface across different orchestration engines.
- **Server-Sent Events.** Run lifecycle changes are emitted as SSE events, so
  clients can follow execution without polling.
- **Lightweight admin console.** The Next.js console lists runs, opens run
  details, renders steps and messages, and subscribes to the live event stream.
- **Contributor-oriented stack.** Python 3.12, FastAPI, Pydantic v2,
  SQLAlchemy 2, Alembic, Redis, `uv`, Next.js and TypeScript. The stack is
  conventional by design.

## Architecture

```
┌───────────────────┐  REST   ┌─────────────────────┐
│  Next.js console  │ ──────▶ │   FastAPI server     │
│  (app/runs/...)   │ ◀─SSE── │  api/v1, services/   │
└───────────────────┘         └──────────┬──────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │ Orchestrator adapter │
                              │  (LangGraph, Echo...)│
                              └──────────┬──────────┘
                                         │ events
                                         ▼
                              ┌──────────────────────┐
                              │  Postgres + Redis    │
                              └──────────────────────┘
```

See [docs/architecture.md](docs/architecture.md) and
[docs/data-model.md](docs/data-model.md) for the service flow, adapter
contract and database model.

## Quick start

Requirements: Docker, [`uv`](https://github.com/astral-sh/uv) and Node.js 20+.

```bash
# 1. Start dependencies
docker compose up -d postgres redis

# 2. Start the backend
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. Start the console
cd ../frontend
npm install
npm run dev
```

Open http://localhost:3000. The default `echo` adapter runs locally and does
not require a model provider key.

## Create a run through the API

Create an agent:

```bash
curl -X POST http://localhost:8000/v1/agents \
  -H "content-type: application/json" \
  -d '{
        "name": "writer",
        "adapter": "langgraph",
        "config": {
          "model": "openai/gpt-4o-mini",
          "system_prompt": "You are a concise technical writer."
        }
      }'
```

Start a run:

```bash
curl -X POST http://localhost:8000/v1/runs \
  -H "content-type: application/json" \
  -d '{"agent_id": "<id from previous response>", "input": {"prompt": "Explain SSE in two sentences."}}'
```

Subscribe to the run event stream:

```bash
curl -N http://localhost:8000/v1/events/<run_id>
```

## Project layout

```
agentflow/
├── backend/                FastAPI runtime + LangGraph adapter
│   ├── app/
│   │   ├── adapters/       orchestrator adapters
│   │   ├── api/v1/         HTTP routes
│   │   ├── core/           configuration and logging
│   │   ├── db/             SQLAlchemy session and base
│   │   ├── events/         in-memory and Redis event bus
│   │   ├── models/         ORM models
│   │   ├── schemas/        Pydantic schemas
│   │   └── services/       run lifecycle service
│   ├── alembic/            database migrations
│   └── tests/
├── frontend/               Next.js admin console
├── docs/                   architecture and data model
└── docker-compose.yml
```

## Adapter interface

Adapters implement a single async method. The runtime passes an
`AdapterContext`; the adapter emits lifecycle events through the context and
returns an `AdapterResult` when execution reaches a terminal state.

```python
from app.adapters.base import AdapterContext, AdapterResult, OrchestratorAdapter
from app.models.run import RunStatus

class MyAdapter(OrchestratorAdapter):
    async def run(self, ctx: AdapterContext) -> AdapterResult:
        await ctx.emit_step_started(index=0, node="think")
        await ctx.emit_message(role="assistant", content="hello")
        await ctx.emit_step_completed(index=0, node="think")
        return AdapterResult(status=RunStatus.SUCCEEDED, output={"ok": True})
```

Register the adapter in `app/adapters/__init__.py`. The API, persistence
model, event stream and console continue to operate through the shared runtime
contract.

## Roadmap

- [x] **Phase 1: Runtime core.** Agents, runs, steps, tool calls,
      checkpoints, SSE, LangGraph and Echo adapters, console MVP.
- [ ] **Phase 2: Observability.** Step timeline, retry and resume actions,
      token and cost summaries.
- [ ] **Phase 3: Extensibility.** Plugin registry, MCP tool adapter,
      official Python SDK and TypeScript SDK.
- [ ] **Phase 4: Production features.** Temporal-backed long-running
      workflows, human approval, RBAC, OpenTelemetry export and deployment
      templates.

## Contributing

Useful contributions at this stage include:

1. Running the quick start and reporting issues with setup or documentation.
2. Implementing additional adapters for orchestration frameworks.
3. Improving the console with execution metrics, trace views or tool-call
   inspection.
4. Adding tests around run lifecycle, event streaming and adapter behavior.

For larger changes, please open an issue or discussion first so the design can
be reviewed before implementation.

## License

Apache 2.0.
