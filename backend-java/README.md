# AgentFlow Java API

Spring Boot 3 implementation of the frontend-facing API surface documented in
[`../docs/api-contract.md`](../docs/api-contract.md). Agent orchestration runs
in the Python worker process (`python -m app.worker` from `../backend`).

## Layout

```
src/main/java/io/agentflow/api/
├── AgentflowApiApplication.java     Spring Boot entrypoint
├── config/                          Jackson, CORS and Redis configuration
├── controller/                      /v1 REST controllers + SSE
├── dto/                             Wire-format DTOs (snake_case)
├── entity/                          JPA entities matching the SQLAlchemy schema
├── jobs/                            Redis-backed job producer + cancel signal
├── repository/                      Spring Data JPA repositories
└── service/                         Agent, Run and Event services
```

The Postgres schema is defined in `backend/alembic/` and applied with Alembic.
JPA runs in `ddl-auto: validate` so the Java server only reads/writes the
existing tables. For local unit tests against H2, JPA creates the schema
in-memory.

## Run locally

```bash
# Against Postgres + Redis from the repo-root docker-compose
mvn spring-boot:run

# Or with a packaged jar
mvn clean package
java -jar target/agentflow-api-0.1.0.jar
```

Environment variables (see [`src/main/resources/application.yml`](src/main/resources/application.yml)):

| Variable                       | Default                                          |
|--------------------------------|--------------------------------------------------|
| `AGENTFLOW_DATABASE_URL`       | `jdbc:postgresql://localhost:5432/agentflow`     |
| `AGENTFLOW_DATABASE_USERNAME`  | `agentflow`                                      |
| `AGENTFLOW_DATABASE_PASSWORD`  | `agentflow`                                      |
| `AGENTFLOW_REDIS_HOST`         | `localhost`                                      |
| `AGENTFLOW_REDIS_PORT`         | `6379`                                           |
| `AGENTFLOW_SERVER_PORT`        | `8000`                                           |
| `AGENTFLOW_JOBS_IMPL`          | `streams` (or `list` for the LPUSH path)         |

The frontend points `/api/*` at `${AGENTFLOW_API_URL}` (defaults to
`http://localhost:8000`).

## Internal protocol with the Python worker

See the "API ↔ worker protocol" section in
[`../docs/api-contract.md`](../docs/api-contract.md). In short:

- jobs (default, at-least-once): `XADD agentflow:jobs:runs * payload <json>`
  (API) / `XREADGROUP` + `XACK` inside consumer group `agentflow-workers`
  (worker), with `XAUTOCLAIM` recovering pending entries left by a crashed
  worker.
- jobs (at-most-once): `LPUSH agentflow:jobs:runs` (API) / `BRPOP`
  (worker). Set `AGENTFLOW_JOBS_IMPL=list` on the API and
  `AGENTFLOW_REDIS_QUEUE_IMPL=list` on the worker.
- cancel: `SET agentflow:cancel:{run_id} 1 EX 86400` (API) / polled by worker
- events: `PUBLISH agentflow:run:{run_id}` (worker) / `SUBSCRIBE` (API SSE)

> Switching between `list` and `streams` requires deleting the existing
> `agentflow:jobs:runs` key in Redis — Streams and LISTs are different data
> types and can't share a key. Drain the queue before flipping the flag, and
> roll both sides together.
