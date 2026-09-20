# Hivemind backend

FastAPI runtime that exposes the agent execution API and a default LangGraph
orchestrator adapter.

## Layout

```
app/
├── adapters/         Orchestrator adapters (Echo, LangGraph, MCP, ...)
├── api/v1/           HTTP routes
├── core/             Config + logging
├── db/               SQLAlchemy session/base
├── events/           In-memory + Redis event bus
├── models/           ORM models
├── runtime/          Adapter-agnostic runtime helpers (memory window, quotas, webhooks, ...)
├── schemas/          Pydantic schemas
├── services/         Run lifecycle service
└── worker/           Queue consumer, cancel registry, sweepers
```

## Develop

```bash
uv sync --all-extras
docker compose -f ../docker-compose.yml up -d postgres redis
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Browse OpenAPI at http://localhost:8000/docs.

### MCP tool adapter

The `mcp` adapter calls MCP servers directly (stdio, SSE, or Streamable HTTP)
and writes standard `ToolCall` rows. Configure `mcp_servers` in agent config
and pass tool calls via `input.tool`/`input.calls` or fixed `config.steps`.
LangGraph graphs can reuse the same MCP bridge via `AdapterToolSurface`.
See [docs/architecture.md](../docs/architecture.md#mcp-tool-bridge).

## Tests

```bash
uv run pytest -q
```

Tests use SQLite by default via `aiosqlite` so they do not require Postgres.
`tests/conftest.py` points `AGENTFLOW_DATABASE_URL` at a throwaway file in a
temp directory rather than `:memory:`: the in-memory URL shares one
connection across every session, which makes the request session and the
run executor's session trample each other. Export `AGENTFLOW_DATABASE_URL`
yourself to run the suite against another database.

The same command runs in CI on pushes to `main` and on pull requests
targeting `main` (`.github/workflows/tests.yml`, together with the Python
and TypeScript SDK tests).
