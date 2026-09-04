#!/usr/bin/env bash
# Commit the index with git commit-tree so `git commit` wrappers cannot inject
# Co-authored-by: Cursor (or any other trailer). Message from stdin.
# Usage: commit-index.sh <<'EOF'
# feat: ...
# EOF
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: not a git repository" >&2
  exit 1
fi

msg="$(cat)"
if [[ -z "${msg//[$' \t\n']/}" ]]; then
  echo "error: empty commit message" >&2
  exit 1
fi

if printf '%s\n' "${msg}" | awk 'tolower($0) ~ /cursor/ { found=1 } END { exit found ? 0 : 1 }'; then
  echo "error: commit message contains forbidden cursor wording" >&2
  exit 1
fi

if [[ -z "$(git diff --cached --name-only)" ]]; then
  echo "error: nothing staged" >&2
  exit 1
fi

current="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "${current}" ]]; then
  echo "error: detached HEAD; check out a branch first" >&2
  exit 1
fi

default_base="main"
if command -v gh >/dev/null 2>&1; then
  detected="$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null || true)"
  if [[ -n "${detected}" ]]; then
    default_base="${detected}"
  fi
fi
if [[ "${current}" == "${default_base}" || "${current}" == "main" || "${current}" == "master" ]]; then
  echo "error: refusing to commit on default branch '${current}'" >&2
  exit 1
fi

tree="$(git write-tree)"
subject="${msg%%$'\n'*}"

if git rev-parse --verify --quiet HEAD >/dev/null; then
  parent="$(git rev-parse HEAD)"
  commit="$(printf '%s\n' "${msg}" | git commit-tree "${tree}" -p "${parent}" -F -)"
  git update-ref -m "commit: ${subject}" HEAD "${commit}" "${parent}"
else
  commit="$(printf '%s\n' "${msg}" | git commit-tree "${tree}" -F -)"
  git update-ref -m "commit: ${subject}" HEAD "${commit}"
fi

body="$(git log -1 --format=%B)"
if printf '%s\n' "${body}" | awk 'tolower($0) ~ /cursor/ { found=1 } END { exit found ? 0 : 1 }'; then
  echo "error: HEAD message still contains cursor after commit-tree" >&2
  git log -1 --format=full >&2
  exit 1
fi

echo "commit: ${commit}"
git log -1 --format=full
