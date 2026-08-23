#!/usr/bin/env bash
# Create or update a single open automation issue by exact title match.
# Usage: upsert_automation_issue.sh <title> <body-file> [label...]
set -euo pipefail

TITLE="${1:?title required}"
BODY_FILE="${2:?body file required}"
shift 2

if [[ ! -f "$BODY_FILE" ]]; then
  echo "Body file not found: $BODY_FILE" >&2
  exit 1
fi

ensure_label() {
  local name="$1"
  gh label create "$name" --color "0E8A16" --description "Automation" --force >/dev/null 2>&1 || true
}

LABELS=("$@")
for label in "${LABELS[@]}"; do
  ensure_label "$label"
done

EXISTING="$(
  gh issue list --state open --limit 100 --json number,title \
    | jq -r --arg t "$TITLE" '.[] | select(.title == $t) | .number' \
    | head -n 1
)"

if [[ -z "$EXISTING" ]]; then
  EXISTING="$(
    gh issue list --state open --search "${TITLE}" --limit 20 --json number,title \
      | jq -r --arg t "$TITLE" '.[] | select(.title == $t) | .number' \
      | head -n 1
  )"
fi

RUN_URL="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID:-unknown}"

if [[ -n "$EXISTING" ]]; then
  echo "Updating issue #${EXISTING}"
  gh issue edit "$EXISTING" --body-file "$BODY_FILE"
  if ((${#LABELS[@]})); then
    ADD_ARGS=()
    for label in "${LABELS[@]}"; do
      ADD_ARGS+=(--add-label "$label")
    done
    gh issue edit "$EXISTING" "${ADD_ARGS[@]}" || true
  fi
  gh issue comment "$EXISTING" --body "Automated refresh from workflow run: ${RUN_URL}"
  echo "ISSUE_NUMBER=${EXISTING}"
else
  echo "Creating issue: ${TITLE}"
  CREATE_ARGS=(issue create --title "$TITLE" --body-file "$BODY_FILE")
  for label in "${LABELS[@]}"; do
    CREATE_ARGS+=(--label "$label")
  done
  URL="$(gh "${CREATE_ARGS[@]}")"
  echo "Created ${URL}"
fi
