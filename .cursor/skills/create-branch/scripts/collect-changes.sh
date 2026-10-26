#!/usr/bin/env bash
# Collect staged / unstaged / untracked changes for create-branch.
# Never prints remotes (they may contain credentials).
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: not a git repository" >&2
  exit 1
fi

branch="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "${branch}" ]]; then
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

on_default="false"
if [[ "${branch}" == "${default_base}" ]]; then
  on_default="true"
fi

staged_stat="$(git diff --cached --stat)"
unstaged_stat="$(git diff --stat)"
untracked="$(git ls-files --others --exclude-standard)"

has_staged="false"
if [[ -n "$(git diff --cached --name-only)" ]]; then
  has_staged="true"
fi

has_unstaged="false"
if [[ -n "$(git diff --name-only)" || -n "${untracked}" ]]; then
  has_unstaged="true"
fi

echo "=== meta ==="
echo "branch: ${branch}"
echo "default_base: ${default_base}"
echo "on_default: ${on_default}"
echo "has_staged: ${has_staged}"
echo "has_unstaged: ${has_unstaged}"
echo

echo "=== status ==="
git status --short --branch
echo

echo "=== staged (index) ==="
if [[ "${has_staged}" == "true" ]]; then
  echo "${staged_stat}"
  echo
  git diff --cached --no-ext-diff
else
  echo "(empty)"
fi
echo

echo "=== unstaged ==="
if [[ -n "$(git diff --name-only)" ]]; then
  echo "${unstaged_stat}"
  echo
  git diff --no-ext-diff
else
  echo "(empty)"
fi
echo

echo "=== untracked ==="
if [[ -n "${untracked}" ]]; then
  echo "${untracked}"
else
  echo "(none)"
fi
