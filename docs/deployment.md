# Production deployment

AgentFlow runs as a Java API + Python worker(s) + Postgres + Redis stack.

## Components

| Component | Image / binary | Role |
| --- | --- | --- |
| `api` | `backend-java` Spring Boot JAR | Frontend-facing REST + SSE; enqueues jobs; signals cancel |
| `worker` | `backend` Python (`python -m app.worker`) | Consumes Redis jobs; runs adapters; writes Postgres |
| `postgres` | Postgres 16 | Durable runs, steps, messages, tool calls, checkpoints |
| `redis` | Redis 7 | Run job stream (default: Streams + consumer group), cancel keys, event pub/sub |

The Alembic migrations in `backend/alembic/` own the database schema. Apply
them before starting `api` or any worker:

```bash
cd backend && uv run alembic upgrade head
```

## Required environment

### Java API (`backend-java`)

| Variable | Production value |
| --- | --- |
| `AGENTFLOW_DATABASE_URL` | `jdbc:postgresql://<host>:5432/agentflow` |
| `AGENTFLOW_DATABASE_USERNAME` | DB user |
| `AGENTFLOW_DATABASE_PASSWORD` | DB password |
| `AGENTFLOW_REDIS_HOST` | Redis host |
| `AGENTFLOW_REDIS_PORT` | `6379` |
| `AGENTFLOW_SERVER_PORT` | `8000` (or behind a load balancer) |
| `AGENTFLOW_JOBS_IMPL` | `streams` (recommended; must match worker) |

### Python worker (`backend`)

| Variable | Production value |
| --- | --- |
| `AGENTFLOW_WORKER_MODE` | `queue` |
| `AGENTFLOW_DATABASE_URL` | `postgresql+asyncpg://<user>:<pass>@<host>:5432/agentflow` |
| `AGENTFLOW_REDIS_URL` | `redis://<host>:6379/0` |
| `AGENTFLOW_REDIS_QUEUE_IMPL` | `streams` (must match `AGENTFLOW_JOBS_IMPL`) |

Optional model-provider keys (`AGENTFLOW_OPENAI_API_KEY`, etc.) are only
needed when running adapters that call external models.

### Frontend

| Variable | Production value |
| --- | --- |
| `AGENTFLOW_API_URL` | Base URL of the Java API (e.g. `https://api.example.com`) |

The Next.js app proxies `/api/*` to this URL in development; in production,
configure your edge or ingress to route API traffic to the Java API.

## Docker Compose (reference stack)

```bash
cd backend && uv sync && uv run alembic upgrade head
docker compose --profile app up --build
```

This starts Postgres, Redis, the Java API (`localhost:8000`), and a single
worker. Scale workers horizontally by running additional `worker` containers
(same Redis consumer group, distinct consumer names).

Health check: `GET /v1/health` should return `{"status":"ok",...}`.

## Startup order

1. Postgres and Redis
2. `alembic upgrade head` (from `backend/`)
3. One or more Python workers (`AGENTFLOW_WORKER_MODE=queue`)
4. Java API server
5. Frontend (or any API client)

Workers may start before the API, but no runs execute until both are healthy
and the schema has been applied.

## CI verification

GitHub Actions job `integration` (see `.github/workflows/ci.yml`) runs:

1. `docker compose --profile app up` against ephemeral Postgres/Redis
2. End-to-end smoke (`scripts/ci/java_stack_smoke.py`) — create agent, run,
   poll until `succeeded`

## Operational notes

- **Queue protocol:** Default is Redis Streams (`AGENTFLOW_JOBS_IMPL=streams` /
  `AGENTFLOW_REDIS_QUEUE_IMPL=streams`). Switching to the LIST protocol
  requires rolling API and workers together and clearing the old key — see
  [api-contract.md](api-contract.md).
- **Horizontal scale:** Add worker replicas; keep a single Java API tier (or
  put it behind a load balancer — SSE subscribers stick to one instance unless
  you add shared pub/sub bridging).
- **Backups:** Postgres holds all durable state; Redis is ephemeral coordination.
- **Logs:** Java API logs Spring Boot output; worker logs structlog from
  `app.worker`.

## What not to run in production

| Avoid | Use instead |
| --- | --- |
| SQLite (`AGENTFLOW_DATABASE_URL` default in dev) | Postgres |
| In-memory event bus (no `AGENTFLOW_REDIS_URL`) | Redis pub/sub |
