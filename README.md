# AgentFlow

> A Python-first runtime layer for multi-agent systems, with persistent run
> state, streaming execution events, and a pluggable orchestration interface.

[中文](README.zh-CN.md) · [Architecture](docs/architecture.md) · [Data model](docs/data-model.md) · [Plan](docs/plan.md)

[License](LICENSE)
[Python](https://www.python.org)

AgentFlow provides the runtime infrastructure around multi-agent applications.
It does not replace frameworks such as LangGraph, AutoGen or CrewAI. Instead,
it gives them a consistent execution model: agents are invoked as runs, runs
produce ordered steps and messages, tool calls are recorded, and every state
change can be streamed to a client.

The project is designed for teams that want to move from an agent prototype to
an inspectable service without committing to a single orchestration framework
or rebuilding persistence, event streaming and operational tooling for each
new agent.

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

AgentFlow focuses on that runtime boundary. The stack pairs a Java/Spring Boot
API for HTTP and SSE with Python workers for adapter execution, SQLAlchemy and
Alembic for persistence, and Redis for job queues and live events.

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
- **Contributor-oriented stack.** Java 21, Spring Boot 3, Python 3.12,
SQLAlchemy 2, Alembic, Redis, `uv`, Next.js and TypeScript.

## Architecture

The HTTP layer that the frontend talks to is a Java/Spring Boot service in
[`backend-java/`](backend-java/). Agent orchestration runs in Python worker
processes in [`backend/`](backend/) that consume a Redis-backed job queue and
drive adapters (LangGraph, Echo, ...) to completion.

```
┌───────────────────┐  REST   ┌──────────────────────┐
│  Next.js console  │ ──────▶ │  Java/Spring Boot API│
│  (app/runs/...)   │ ◀─SSE── │  /v1/* + SSE bridge  │
└───────────────────┘         └──────────┬───────────┘
                                         │ jobs / cancel / events (Redis)
                                         ▼
                              ┌──────────────────────┐
                              │ Python worker (uv)   │
                              │  app.worker.runner   │
                              └──────────┬───────────┘
                                         ▼
                              ┌──────────────────────┐
                              │ Orchestrator adapter │
                              │  (LangGraph, Echo...)│
                              └──────────┬───────────┘
                                         ▼
                              ┌──────────────────────┐
                              │  Postgres (state)    │
                              └──────────────────────┘
```

See:

- [docs/api-contract.md](docs/api-contract.md) — frozen `/v1` HTTP contract
  and the API↔worker Redis protocol.
- [docs/deployment.md](docs/deployment.md) — production runbook.
- [docs/architecture.md](docs/architecture.md) and
  [docs/data-model.md](docs/data-model.md) — runtime topology and database
  model.

## Quick start

Requirements: Docker, [`uv`](https://github.com/astral-sh/uv), Node.js 20+,
JDK 21 and Maven 3.9+.

```bash
# Infrastructure
docker compose up -d postgres redis

# Database schema
cd backend && uv sync && uv run alembic upgrade head

# Worker (separate shell)
AGENTFLOW_WORKER_MODE=queue uv run python -m app.worker

# Java API (separate shell)
cd ../backend-java && mvn spring-boot:run

# Frontend (separate shell)
cd ../frontend && npm install && npm run dev
```

Or via Docker Compose:

```bash
cd backend && uv sync && uv run alembic upgrade head
docker compose --profile app up --build
```

Open [http://localhost:3000](http://localhost:3000). The default `echo` adapter runs locally and does
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
├── backend/                Python runtime: adapters, worker, Alembic schema
│   ├── app/
│   │   ├── adapters/       orchestrator adapters
│   │   ├── core/           configuration and logging
│   │   ├── db/             SQLAlchemy session and base
│   │   ├── events/         in-memory and Redis event bus
│   │   ├── models/         ORM models
│   │   ├── schemas/        Pydantic schemas (shared shapes)
│   │   ├── services/       run lifecycle helpers
│   │   └── worker/         queue, cancel registry, worker loop
│   ├── alembic/            database schema (source of truth)
│   └── tests/
├── backend-java/           Spring Boot API server (frontend-facing)
│   └── src/main/java/io/agentflow/api/
│       ├── controller/     /v1 REST + SSE controllers
│       ├── dto/            wire-format DTOs (snake_case)
│       ├── entity/         JPA entities
│       ├── jobs/           Redis job producer + cancel signal
│       ├── repository/     Spring Data JPA repositories
│       └── service/        agent / run / event services
├── frontend/               Next.js admin console
├── docs/                   architecture, deployment, API contract
└── docker-compose.yml      profiles: default (infra), `app` (API + worker)
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

Register the adapter in `app/adapters/__init__.py`. Workers pick it up
automatically; the API, persistence model, event stream and console stay on
the shared runtime contract.

## Current architecture (summary)

AgentFlow is a **split runtime**: a Java API tier, a Python execution tier,
and shared infrastructure.


| Layer    | Stack                         | Responsibility                                         |
| -------- | ----------------------------- | ------------------------------------------------------ |
| Console  | Next.js 15, React Query, SSE  | Run/agent management, live event stream                |
| API      | Java 21, Spring Boot 3, JPA   | REST `/v1/*`, SSE bridge, job enqueue, cancel          |
| Worker   | Python asyncio, `RunExecutor` | Consume Redis jobs, run adapters, write Postgres       |
| Adapters | LangGraph, Echo (+ registry)  | Framework-specific orchestration behind one interface  |
| State    | Postgres 16, Alembic          | Durable runs, steps, messages, tool calls, checkpoints |
| Messaging| Redis Streams + pub/sub       | At-least-once job queue, cancel keys, live events      |


**Data flow:** `POST /v1/runs` → API writes `pending` row → Redis job → worker
runs adapter → rows + events → SSE to console. Postgres is the source of truth;
Redis is ephemeral coordination only.

See [docs/architecture.md](docs/architecture.md),
[docs/deployment.md](docs/deployment.md) and
[docs/api-contract.md](docs/api-contract.md) for the full contract and
API↔worker protocol.

## License

Apache 2.0.
