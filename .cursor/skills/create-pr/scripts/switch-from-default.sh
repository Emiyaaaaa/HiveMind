#!/usr/bin/env bash
# Create and switch to a new branch from the current default-branch HEAD.
# Usage: switch-from-default.sh <branch-name>
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: switch-from-default.sh <branch-name>" >&2
  exit 2
fi

branch_name="$1"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: not a git repository" >&2
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

if [[ "${current}" != "${default_base}" ]]; then
  echo "error: current branch is '${current}', not default '${default_base}'" >&2
  exit 1
fi

if [[ ! "${branch_name}" =~ ^[a-z0-9]+[a-z0-9/_-]*[a-z0-9]$ ]]; then
  echo "error: invalid branch name '${branch_name}' (use lowercase, digits, /, -, _)" >&2
  exit 1
fi

case "${branch_name}" in
  main|master|HEAD|"${default_base}")
    echo "error: refusing to create branch named '${branch_name}'" >&2
    exit 1
    ;;
esac

if git show-ref --verify --quiet "refs/heads/${branch_name}"; then
  echo "error: local branch '${branch_name}' already exists" >&2
  exit 1
fi

if git show-ref --verify --quiet "refs/remotes/origin/${branch_name}"; then
  echo "error: origin/${branch_name} already exists; pick another name" >&2
  exit 1
fi

git switch -c "${branch_name}"
echo "switched: ${current} -> ${branch_name}"
