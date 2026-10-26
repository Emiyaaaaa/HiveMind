#!/usr/bin/env bash
# Generate Python and TypeScript REST stubs from openapi/openapi.yaml.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SPEC="${ROOT}/openapi/openapi.yaml"
PY_OUT="${ROOT}/sdk/python/generated"
TS_OUT="${ROOT}/sdk/typescript/generated"

if [[ ! -f "${SPEC}" ]]; then
  echo "Missing ${SPEC}; run scripts/gen/export-openapi.sh first." >&2
  exit 1
fi

rm -rf "${PY_OUT}" "${TS_OUT}"
mkdir -p "${PY_OUT}" "${TS_OUT}"

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required to run @openapitools/openapi-generator-cli" >&2
  exit 1
fi

GENERATOR_CLI_VERSION="${OPENAPI_GENERATOR_CLI_VERSION:-2.20.0}"
GENERATOR_ENGINE_VERSION="${OPENAPI_GENERATOR_VERSION:-7.14.0}"

run_generator() {
  local generator="$1"
  shift
  local output="$1"
  shift

  if command -v java >/dev/null 2>&1; then
    OPENAPI_GENERATOR_VERSION="${GENERATOR_ENGINE_VERSION}" \
      npx --yes "@openapitools/openapi-generator-cli@${GENERATOR_CLI_VERSION}" generate \
      -i "${SPEC}" \
      -g "${generator}" \
      -o "${output}" \
      "$@"
    return
  fi

  if command -v docker >/dev/null 2>&1; then
    docker run --rm \
      -v "${ROOT}:/local" \
      "openapitools/openapi-generator-cli:v${GENERATOR_ENGINE_VERSION}" generate \
      -i "/local/openapi/openapi.yaml" \
      -g "${generator}" \
      -o "/local/${output#${ROOT}/}" \
      "$@"
    return
  fi

  echo "Java or Docker is required to run OpenAPI Generator." >&2
  exit 1
}

run_generator python "${PY_OUT}" \
  --package-name agentflow_generated \
  --additional-properties=projectName=agentflow-sdk,packageVersion=0.1.0,library=urllib3

run_generator typescript-fetch "${TS_OUT}" \
  --additional-properties=npmName=@agentflow/sdk-generated,npmVersion=0.1.0,supportsES6=true,typescriptThreePlus=true

echo "Generated Python stubs -> ${PY_OUT}"
echo "Generated TypeScript stubs -> ${TS_OUT}"
