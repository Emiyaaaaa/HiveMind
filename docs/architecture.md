# Architecture

AgentFlow is intentionally small. Every concept maps to a single file or a
small package so contributors can read the whole runtime in an afternoon.

## Layers

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
│ API (FastAPI)                                                │
│   api/v1/agents.py      CRUD agents                           │
│   api/v1/runs.py        create / get / cancel / list runs     │
│   api/v1/events.py      SSE per-run event stream              │
└───────────────────┬──────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────────┐
│ Services                                                     │
│   services/run_service.py                                     │
│     - mutates run state                                       │
│     - spawns adapter task with its own session                │
│     - translates adapter events into rows + broadcasts        │
└───────────────────┬──────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────┐    ┌──────────────────────────────┐
│ Adapters               │    │ Event bus                    │
│   adapters/base.py     │    │   events/bus.py              │
│   adapters/echo.py     │    │     - in-memory (default)    │
│   adapters/langgraph.py│    │     - redis (when configured)│
└────────────────────────┘    └──────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────────┐
│ Persistence (SQLAlchemy 2 async)                             │
│   models/agent.py       Agent                                 │
│   models/run.py         Run, Step, Message, ToolCall, Checkpoint│
└──────────────────────────────────────────────────────────────┘
```

## Request → run lifecycle

1. Client `POST /v1/runs` with `agent_id` and `input`.
2. `RunService.create_run` writes a `Run(status=pending)` and broadcasts
   `run.created`.
3. `RunService.start_run` spawns a background `asyncio.Task` that opens a new
   DB session and invokes the configured `OrchestratorAdapter`.
4. The adapter emits lifecycle events via `AdapterContext.emit_*`. The
   service writes each event to Postgres and publishes a `RunEvent` on the
   bus.
5. Subscribers of `GET /v1/events/{run_id}` see the same events as SSE.
6. When the adapter returns, the service writes the terminal status and
   broadcasts `run.completed` / `run.failed` / `run.cancelled`.

## Why per-task sessions?

SQLAlchemy async sessions are not safe for concurrent use. The request that
created a run keeps reading rows (and refreshing relations), so the adapter
task must own a separate session. `RunService` carries a session factory and
opens a fresh `AsyncSession` for the background work.

## Adding an adapter

1. Subclass `OrchestratorAdapter` in `app/adapters/`.
2. Implement `async def run(self, ctx: AdapterContext) -> AdapterResult`.
3. Emit events through `ctx.emit_step_started`, `ctx.emit_message`, etc.
4. Register it in `app/adapters/__init__.py` via `register_adapter`.

No changes are needed in the DB schema, the API, or the frontend.
