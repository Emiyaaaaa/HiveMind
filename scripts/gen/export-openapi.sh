#!/usr/bin/env bash
# Export the AgentFlow OpenAPI spec from the Spring Boot API (springdoc).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${ROOT}/openapi/openapi.yaml"
PORT="${AGENTFLOW_SERVER_PORT:-18000}"
HEALTH_URL="http://127.0.0.1:${PORT}/v1/health"
SPEC_URL="http://127.0.0.1:${PORT}/v3/api-docs.yaml"

mkdir -p "$(dirname "$OUT")"

cd "${ROOT}/backend-java"

mvn -q -DskipTests package

AGENTFLOW_SERVER_PORT="${PORT}" \
  mvn -q -DskipTests spring-boot:run \
  -Dspring-boot.run.profiles=openapi \
  -Dspring-boot.run.jvmArguments="-Dserver.port=${PORT}" &
PID=$!

cleanup() {
  kill "${PID}" 2>/dev/null || true
  wait "${PID}" 2>/dev/null || true
}
trap cleanup EXIT

python3 "${ROOT}/scripts/ci/wait_for_http.py" "${HEALTH_URL}" 180

curl -fsS "${SPEC_URL}" -o "${OUT}"
echo "Wrote ${OUT}"
