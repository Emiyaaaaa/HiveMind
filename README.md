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

The HTTP layer that the frontend talks to is a Java/Spring Boot service in
`[backend-java/](backend-java/)`. Agent orchestration stays in Python; a
worker process in `[backend/](backend/)` consumes a Redis-backed job queue
and drives adapters (LangGraph, Echo, ...) to completion.

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

The legacy FastAPI server in `[backend/](backend/)` still exists. It runs
in `inline` mode (the default `AGENTFLOW_WORKER_MODE`), executes adapter
runs in-process, and is what the test suite exercises. Switch a deployment
to the Java API by setting `AGENTFLOW_WORKER_MODE=queue` on the worker and
pointing the frontend at the Java server (port `8000`).

See:

- [docs/api-contract.md](docs/api-contract.md) — frozen `/v1` contract that
both backends must implement, plus the Java↔Python Redis protocol.
- [docs/migration-verification.md](docs/migration-verification.md) — what
is auto-verified, plus the manual Java/integration smoke test.
- [docs/architecture.md](docs/architecture.md) and
[docs/data-model.md](docs/data-model.md) — adapter contract and database
model.

## Quick start

Requirements: Docker, `[uv](https://github.com/astral-sh/uv)` and Node.js 20+.
The Java API server additionally needs JDK 21 and Maven 3.9+.

### Option A — Legacy FastAPI (single process, no Java)

```bash
docker compose up -d postgres redis
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

cd ../frontend && npm install && npm run dev
```

### Option B — Java API + Python worker (target architecture)

```bash
# Infrastructure
docker compose up -d postgres redis

# DB schema (Python owns Alembic)
cd backend && uv sync && uv run alembic upgrade head

# Worker (queue mode pulls jobs from Redis)
AGENTFLOW_WORKER_MODE=queue uv run python -m app.worker

# Java API (separate shell)
cd ../backend-java && mvn spring-boot:run

# Frontend (separate shell)
cd ../frontend && npm install && npm run dev
```

Or via docker compose: `docker compose --profile java up --build` brings up
postgres, redis, the Java API and the Python worker together.

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
├── backend/                Python runtime, adapters, worker, legacy FastAPI
│   ├── app/
│   │   ├── adapters/       orchestrator adapters
│   │   ├── api/v1/         legacy FastAPI HTTP routes (inline mode)
│   │   ├── core/           configuration and logging
│   │   ├── db/             SQLAlchemy session and base
│   │   ├── events/         in-memory and Redis event bus
│   │   ├── models/         ORM models
│   │   ├── schemas/        Pydantic schemas
│   │   ├── services/       run lifecycle service
│   │   └── worker/         queue + cancel registry + standalone worker loop
│   ├── alembic/            database migrations (source of truth for the schema)
│   └── tests/
├── backend-java/           Spring Boot 3 API server (frontend-facing)
│   └── src/main/java/io/agentflow/api/
│       ├── controller/     /v1 REST + SSE controllers
│       ├── dto/            wire-format DTOs (snake_case)
│       ├── entity/         JPA entities mapping the same Postgres tables
│       ├── jobs/           Redis job producer + cancel signal
│       ├── repository/     Spring Data JPA repositories
│       └── service/        agent / run / event services
├── frontend/               Next.js admin console
├── docs/                   architecture, data model, API contract, verification
└── docker-compose.yml      profiles: default (legacy), `java`, `full`
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

## Current architecture (summary)

AgentFlow is a **split runtime**: a frontend-facing API tier, a Python
execution tier, and shared infrastructure.


| Layer        | Stack                         | Responsibility                                         |
| ------------ | ----------------------------- | ------------------------------------------------------ |
| Console      | Next.js 15, React Query, SSE  | Run/agent management, live event stream                |
| API (target) | Java 21, Spring Boot 3, JPA   | REST `/v1/`*, SSE bridge, job enqueue, cancel          |
| API (legacy) | Python 3.12, FastAPI          | Same contract; inline adapter execution for dev/CI     |
| Worker       | Python asyncio, `RunExecutor` | Consume Redis jobs, run adapters, write Postgres       |
| Adapters     | LangGraph, Echo (+ registry)  | Framework-specific orchestration behind one interface  |
| State        | Postgres 16, Alembic          | Durable runs, steps, messages, tool calls, checkpoints |
| Messaging    | Redis Streams + pub/sub       | At-least-once job queue, cancel keys, live events      |


**Data flow:** `POST /v1/runs` → API writes `pending` row → Redis job → worker
runs adapter → rows + events → SSE to console. Postgres is the source of truth;
Redis is ephemeral coordination only.

**Deployment modes:**

- **Inline (default):** single FastAPI process — good for local dev and pytest.
- **Queue (target):** Java API + N Python workers — horizontal scale, production path.

See [docs/architecture.md](docs/architecture.md) and  
[docs/api-contract.md](docs/api-contract.md) for the full contract and Java↔Python  
protocol.

## License

Apache 2.0.