# AgentFlow Java API

Spring Boot 3 implementation of the frontend-facing API surface documented in
[`../docs/api-contract.md`](../docs/api-contract.md). This server replaces the
Python FastAPI HTTP layer; agent orchestration continues to run in the Python
worker process (`python -m app.worker` from `../backend`).

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

The Postgres schema is owned by the Python side and managed with Alembic. JPA
runs in `ddl-auto: validate` so the Java server only reads/writes the existing
tables. For local development against H2 we still let JPA create the schema.

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

The frontend already points `/api/*` at `${AGENTFLOW_API_URL}` (defaults to
`http://localhost:8000`), so once this server is running on port `8000` the
Next.js console works against it without changes.

## Internal protocol with the Python worker

See the "Java ↔ Python protocol" section in
[`../docs/api-contract.md`](../docs/api-contract.md). In short:

- jobs: `LPUSH agentflow:jobs:runs` (Java) / `BRPOP` (worker)
- cancel: `SET agentflow:cancel:{run_id} 1 EX 86400` (Java) / polled by worker
- events: `PUBLISH agentflow:run:{run_id}` (worker) / `SUBSCRIBE` (Java SSE)
