.PHONY: help up down backend frontend migrate test lint format

help:
	@echo "Available targets:"
	@echo "  up        - start postgres + redis"
	@echo "  down      - stop infrastructure"
	@echo "  backend   - run FastAPI dev server"
	@echo "  frontend  - run Next.js dev server"
	@echo "  migrate   - run alembic migrations"
	@echo "  test      - run backend tests"
	@echo "  lint      - run ruff + tsc"
	@echo "  format    - run ruff format"

up:
	docker compose up -d postgres redis

down:
	docker compose down

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

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
