# Java API Migration — Verification Notes

This is the checklist that backs the "verification" step of the Java API
migration plan. It records what is automatically verified, what needs a
running Postgres / Redis / JDK to verify, and the manual smoke procedures
for the frontend.

## Verified locally (in this repo)

The Python side of the new wiring runs in CI via the existing `pytest`
suite. After the migration the suite covers:

| Test                                                           | What it proves |
|----------------------------------------------------------------|----------------|
| `tests/test_health.py::test_health`                            | The legacy FastAPI surface still serves `/v1/health` and reports both adapters. |
| `tests/test_runs.py::test_echo_run_end_to_end`                 | The "inline" execution path (FastAPI process owns the asyncio task) still drives a run from `pending` to `succeeded` end-to-end after the executor refactor. |
| `tests/test_worker_queue.py::test_start_run_enqueues_job_in_queue_mode` | When `worker_mode=queue`, `RunService.start_run` does **not** start an inline task; it pushes a `RunJob` onto the shared queue and the run stays `pending`. This is the contract the Java API depends on. |
| `tests/test_worker_queue.py::test_executor_drives_run_to_succeeded` | The standalone `RunExecutor` (used by `python -m app.worker`) runs the same adapters, writes the same DB rows, and produces the same terminal state as the inline path. |
| `tests/test_worker_queue.py::test_cancel_registry_aborts_execution` | Setting the cancel signal mid-flight aborts the adapter, rolls the session back cleanly, and finalises the run as `cancelled`. This validates the protocol the Java `CancelSignal` writes to. |
| `tests/test_worker_queue.py::test_runjob_round_trip`           | The Python `RunJob` JSON is stable — Java will be able to round-trip the same payload through Jackson with snake_case keys. |

Run them with:

```bash
cd backend
uv run pytest -q
uv run ruff check .
```

## Needs a JDK + Postgres + Redis

The Java API server in [`backend-java/`](../backend-java/) ships a unit
test (`HealthControllerTest`) that runs entirely inside `MockMvc`, plus
the configuration plumbing to talk to Postgres and Redis. Build and test
it with:

```bash
cd backend-java
mvn -B verify
```

For an integration-level check against a real database and Redis, use the
`java` profile of the repo-root compose file. It boots Postgres, Redis,
the Spring Boot API server (`api-java`) and the Python worker process:

```bash
docker compose --profile java up --build
```

That brings up:

- `postgres` (5432) and `redis` (6379)
- `api-java` (Spring Boot, exposed on `localhost:8000`)
- `worker` (Python `app.worker.runner`, no exposed port)

Once running, the existing manual smoke commands from the project README
work without modification because the URL and JSON shapes are identical:

```bash
# Create an agent
curl -X POST http://localhost:8000/v1/agents \
  -H 'content-type: application/json' \
  -d '{"name":"echo-bot","adapter":"echo","config":{"delay":0}}'

# Start a run (returns 202 immediately; Java enqueues, worker executes)
curl -X POST http://localhost:8000/v1/runs \
  -H 'content-type: application/json' \
  -d '{"agent_id":"<id>","input":{"prompt":"hi"}}'

# Stream events
curl -N http://localhost:8000/v1/events/<run_id>

# Cancel
curl -X POST http://localhost:8000/v1/runs/<run_id>/cancel
```

## Frontend smoke test

No code change is required in the Next.js console. `frontend/next.config.mjs`
already proxies `/api/*` to `${AGENTFLOW_API_URL}` (default
`http://localhost:8000`).

1. Start the Java API server and the Python worker (either via the compose
   profile above, or with `make backend-java` and `make worker` in two
   shells against `make up` infrastructure).
2. `cd frontend && npm install && npm run dev`.
3. Open http://localhost:3000 and verify:
   - The agents list loads (proxied `GET /v1/agents`).
   - Creating an agent succeeds (`POST /v1/agents`).
   - Creating a run returns immediately and the run row appears in
     `pending`, then transitions to `running`/`succeeded` as the worker
     consumes the job.
   - The run detail page receives SSE updates (steps, messages, terminal
     event).
   - Cancelling a long-running run (e.g. the `langgraph` adapter against a
     real model) flips the run to `cancelled`.

## Contract parity with the legacy FastAPI

To assert that the Java implementation does not drift from the Pydantic
schemas, point both servers at the same Postgres database and run the same
requests against each. The expected diff is empty:

```bash
# Terminal A (legacy FastAPI on :8001)
AGENTFLOW_SERVER_PORT=8001 make backend

# Terminal B (Java API on :8002)
AGENTFLOW_SERVER_PORT=8002 make backend-java

# Compare
diff <(curl -s http://localhost:8001/v1/agents) \
     <(curl -s http://localhost:8002/v1/agents)
```

Field-by-field equivalence is ensured by:

- Snake_case JSON via [`io.agentflow.api.config.JacksonConfig`](../backend-java/src/main/java/io/agentflow/api/config/JacksonConfig.java).
- The same DB schema (Alembic-owned) consumed by both backends.
- ISO-8601 timestamps via `JavaTimeModule` + `WRITE_DATES_AS_TIMESTAMPS=false`.
- Identical lifecycle: PENDING is owned by the API, every other transition
  by the worker, persisted in the shared Postgres tables.
