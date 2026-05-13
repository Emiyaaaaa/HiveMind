.PHONY: help up down backend backend-java worker frontend migrate test lint format

help:
	@echo "Available targets:"
	@echo "  up           - start postgres + redis"
	@echo "  down         - stop infrastructure"
	@echo "  backend      - run FastAPI dev server (inline mode)"
	@echo "  backend-java - run Spring Boot API server"
	@echo "  worker       - run Python agent worker (queue mode)"
	@echo "  frontend     - run Next.js dev server"
	@echo "  migrate      - run alembic migrations"
	@echo "  test         - run backend tests"
	@echo "  lint         - run ruff + tsc"
	@echo "  format       - run ruff format"

up:
	docker compose up -d postgres redis

down:
	docker compose down

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

backend-java:
	cd backend-java && mvn spring-boot:run

worker:
	cd backend && AGENTFLOW_WORKER_MODE=queue uv run python -m app.worker

frontend:
	cd frontend && npm run dev

migrate:
	cd backend && uv run alembic upgrade head

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

format:
	cd backend && uv run ruff format .
