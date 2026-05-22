.PHONY: help up down api worker frontend db-schema test lint format integration

help:
	@echo "Available targets:"
	@echo "  up           - start postgres + redis"
	@echo "  down         - stop infrastructure"
	@echo "  api          - run Spring Boot API server"
	@echo "  worker       - run Python agent worker"
	@echo "  frontend     - run Next.js dev server"
	@echo "  db-schema    - apply Alembic schema to Postgres"
	@echo "  test         - run backend unit tests"
	@echo "  integration  - compose app profile + end-to-end smoke test"
	@echo "  lint         - run ruff + tsc"
	@echo "  format       - run ruff format"

up:
	docker compose up -d postgres redis

down:
	docker compose down

api:
	cd backend-java && mvn spring-boot:run

worker:
	cd backend && AGENTFLOW_WORKER_MODE=queue uv run python -m app.worker

frontend:
	cd frontend && npm run dev

db-schema:
	cd backend && uv run alembic upgrade head

test:
	cd backend && uv run pytest -q

integration:
	docker compose up -d postgres redis
	cd backend && uv sync --all-extras && uv run alembic upgrade head
	docker compose --profile app up -d --build
	cd backend && \
	uv run python ../scripts/ci/wait_for_http.py http://localhost:8000/v1/health 240 && \
	uv run python ../scripts/ci/java_stack_smoke.py http://localhost:8000

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

format:
	cd backend && uv run ruff format .
