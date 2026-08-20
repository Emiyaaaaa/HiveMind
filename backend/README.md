# AgentFlow backend

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
├── schemas/          Pydantic schemas
└── services/         Run lifecycle service
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
