#!/usr/bin/env bash
# Per-boot reconciliation: bring up PostgreSQL and Redis, ensure the
# application role/database exist, and apply the Alembic schema (the source
# of truth the Java API validates against). Idempotent and safe to re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PATH="$HOME/.local/bin:$PATH"

echo "==> Starting PostgreSQL 16 cluster"
sudo pg_ctlcluster 16 main start 2>/dev/null || true
for _ in $(seq 1 30); do
  pg_isready -h localhost -q && break
  sleep 1
done

echo "==> Ensuring agentflow role and database exist"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='agentflow'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE agentflow LOGIN PASSWORD 'agentflow';"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='agentflow'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE DATABASE agentflow OWNER agentflow;"

echo "==> Starting Redis"
if ! redis-cli ping >/dev/null 2>&1; then
  # ``service redis-server start`` can exit 0 even when redis fails to come up
  # (for example when a snapshot baked /var/log/redis owned by root), so never
  # trust its exit code: try it, then verify and fall back to a user-owned
  # daemon writing to a writable location.
  sudo service redis-server start >/dev/null 2>&1 || true
  sleep 1
  if ! redis-cli ping >/dev/null 2>&1; then
    redis-server --daemonize yes --dir /tmp --logfile /tmp/agentflow-redis.log
  fi
fi
for _ in $(seq 1 30); do
  redis-cli ping >/dev/null 2>&1 && break
  sleep 1
done
if ! redis-cli ping >/dev/null 2>&1; then
  echo "ERROR: Redis did not become reachable on localhost:6379" >&2
  exit 1
fi

echo "==> Applying database schema (alembic upgrade head)"
(cd backend && AGENTFLOW_DATABASE_URL="postgresql+asyncpg://agentflow:agentflow@localhost:5432/agentflow" \
  uv run alembic upgrade head)

echo "==> start.sh complete (postgres + redis ready, schema applied)"
