#!/usr/bin/env bash
# Collect git context for create-pr. Prints structured sections; never prints remotes
# (they may contain credentials).
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

base_ref=""
if git show-ref --verify --quiet "refs/remotes/origin/${default_base}"; then
  base_ref="origin/${default_base}"
elif git show-ref --verify --quiet "refs/heads/${default_base}"; then
  base_ref="${default_base}"
else
  echo "error: cannot find base branch ${default_base}" >&2
  exit 1
fi

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
ahead_behind=""
if [[ -n "${upstream}" ]]; then
  ahead_behind="$(git rev-list --left-right --count "${upstream}...HEAD" 2>/dev/null || true)"
fi

existing_pr=""
if command -v gh >/dev/null 2>&1; then
  existing_pr="$(gh pr view --json url,state --jq '"\(.state) \(.url)"' 2>/dev/null || true)"
fi

on_default="false"
if [[ "${branch}" == "${default_base}" ]]; then
  on_default="true"
fi

echo "=== meta ==="
echo "branch: ${branch}"
echo "default_base: ${default_base}"
echo "on_default: ${on_default}"
echo "base_ref: ${base_ref}"
echo "upstream: ${upstream:-none}"
if [[ -n "${ahead_behind}" ]]; then
  behind="${ahead_behind%%$'\t'*}"
  ahead="${ahead_behind##*$'\t'}"
  echo "ahead: ${ahead}"
  echo "behind: ${behind}"
fi
echo "existing_pr: ${existing_pr:-none}"
echo

echo "=== status ==="
git status --short --branch
echo

echo "=== HEAD (latest git record) ==="
git log -1 --format=fuller
echo
git show --stat --format= HEAD
echo

echo "=== commits ${base_ref}..HEAD ==="
if git merge-base "${base_ref}" HEAD >/dev/null 2>&1; then
  git log --oneline "${base_ref}..HEAD"
  echo
  echo "=== diffstat ${base_ref}...HEAD ==="
  git diff --stat "${base_ref}...HEAD"
else
  echo "(no merge-base; using HEAD only)"
fi
