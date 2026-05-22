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
│   adapters/echo.py     │    │     - redis pub/sub (prod)   │
│   adapters/langgraph.py│    │     - in-memory (unit tests) │
└────────────────────────┘    └──────────────────────────────┘
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
   writes each event to Postgres and publishes a `RunEvent` on the Redis
   channel `agentflow:run:{run_id}`.
5. The Java SSE controller relays those events to subscribers of
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

1. Subclass `OrchestratorAdapter` in `app/adapters/`.
2. Implement `async def run(self, ctx: AdapterContext) -> AdapterResult`.
3. Emit events through `ctx.emit_step_started`, `ctx.emit_message`, etc.
4. Register it in `app/adapters/__init__.py` via `register_adapter`.

No changes are needed in the DB schema, the `/v1` contract, or the frontend.
Workers pick up new adapters through the shared Python adapter registry.

## Unit tests

The Python test suite in `backend/tests/` exercises adapter and queue logic
with an in-process ASGI client and in-memory or fake Redis. That harness is
not part of the production topology.
