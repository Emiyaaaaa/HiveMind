#!/usr/bin/env bash
# Idempotent environment bootstrap for AgentFlow.
# Installs system services (PostgreSQL, Redis), build tools (Maven, uv) and
# project dependencies for the Python worker, Java API and Next.js console.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Installing system packages (postgresql, redis, maven)"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
  postgresql postgresql-client redis-server maven

echo "==> Ensuring uv is installed"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "==> Python worker dependencies (uv sync)"
(cd backend && uv sync --all-extras)

echo "==> Frontend console dependencies (npm ci)"
(cd frontend && npm ci)

echo "==> Warming Java API build cache (mvn compile)"
(cd backend-java && mvn -q -DskipTests compile)

echo "==> install.sh complete"
