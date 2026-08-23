#!/usr/bin/env bash
# Collect outdated dependency reports for npm / Python (uv) / Maven.
# Writes markdown to the path given as $1 (default: outdated-deps-report.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-outdated-deps-report.md}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

section() {
  local title="$1"
  local body_file="$2"
  {
    echo "## ${title}"
    echo
    if [[ ! -s "$body_file" ]]; then
      echo "_No outdated packages reported (or scan produced no output)._"
    else
      echo '```'
      cat "$body_file"
      echo '```'
    fi
    echo
  } >>"$OUT"
}

: >"$OUT"
{
  echo "# Outdated dependencies report"
  echo
  echo "Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
  echo
  echo "This issue is updated by the scheduled \`outdated-deps\` workflow."
  echo "Dependabot may also open upgrade PRs for the same ecosystems."
  echo
} >>"$OUT"

# --- frontend (npm) ---
if [[ -f "$ROOT/frontend/package-lock.json" ]]; then
  (
    cd "$ROOT/frontend"
    npm ci --ignore-scripts >/dev/null 2>&1 || npm install --ignore-scripts >/dev/null 2>&1
    # npm outdated exits 1 when outdated packages exist
    npm outdated --long >"$TMP/npm.txt" 2>&1 || true
  )
  section "Frontend (npm)" "$TMP/npm.txt"
else
  echo "## Frontend (npm)" >>"$OUT"
  echo >>"$OUT"
  echo "_Skipped: no package-lock.json._" >>"$OUT"
  echo >>"$OUT"
fi

# --- backend (uv / pip) ---
if [[ -f "$ROOT/backend/pyproject.toml" ]]; then
  (
    cd "$ROOT/backend"
    uv sync --all-extras >/dev/null 2>&1
    uv pip list --outdated >"$TMP/backend-pip.txt" 2>&1 || true
  )
  section "Backend (Python / uv)" "$TMP/backend-pip.txt"
fi

# --- integrations/pydantic-ai ---
if [[ -f "$ROOT/integrations/pydantic-ai/pyproject.toml" ]]; then
  (
    cd "$ROOT/integrations/pydantic-ai"
    uv sync >/dev/null 2>&1 || uv pip install -e ".[dev]" >/dev/null 2>&1 || true
    uv pip list --outdated >"$TMP/integ-pip.txt" 2>&1 || true
  )
  section "integrations/pydantic-ai (Python / uv)" "$TMP/integ-pip.txt"
fi

# --- backend-java (Maven) ---
if [[ -f "$ROOT/backend-java/pom.xml" ]]; then
  (
    cd "$ROOT/backend-java"
    mvn -B -q \
      org.codehaus.mojo:versions-maven-plugin:2.17.1:display-dependency-updates \
      -DprocessDependencyManagement=true \
      >"$TMP/maven.txt" 2>&1 || true
  )
  section "backend-java (Maven dependency updates)" "$TMP/maven.txt"
fi

echo "_End of report._" >>"$OUT"
echo "Wrote $OUT"
