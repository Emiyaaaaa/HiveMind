#!/usr/bin/env bash
# Rewrite BASE..HEAD with git commit-tree, stripping any cursor wording from
# messages (including injected Co-authored-by: Cursor). Linear history only.
# Prints rewritten=true|false. Usage: scrub-commits.sh <base_ref>
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: scrub-commits.sh <base_ref>" >&2
  exit 2
fi

base_ref="$1"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: not a git repository" >&2
  exit 1
fi

if ! git rev-parse --verify --quiet "${base_ref}" >/dev/null; then
  echo "error: unknown base_ref '${base_ref}'" >&2
  exit 1
fi

current="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "${current}" ]]; then
  echo "error: detached HEAD; check out a branch first" >&2
  exit 1
fi
if [[ "${current}" == "main" || "${current}" == "master" ]]; then
  echo "error: refusing to rewrite default branch '${current}'" >&2
  exit 1
fi

strip_cursor_lines() {
  awk '
    tolower($0) ~ /cursor/ { next }
    { lines[++n] = $0 }
    END {
      while (n > 0 && lines[n] ~ /^[ \t]*$/) n--
      for (i = 1; i <= n; i++) print lines[i]
    }
  '
}

has_cursor() {
  awk 'tolower($0) ~ /cursor/ { found=1 } END { exit found ? 0 : 1 }'
}

if ! git merge-base --is-ancestor "${base_ref}" HEAD; then
  echo "error: ${base_ref} is not an ancestor of HEAD" >&2
  exit 1
fi

if ! git log "${base_ref}..HEAD" --format=%B | has_cursor; then
  echo "rewritten: false"
  exit 0
fi

if [[ -n "$(git rev-list --min-parents=2 "${base_ref}..HEAD")" ]]; then
  echo "error: merge commits in ${base_ref}..HEAD; cannot scrub automatically" >&2
  exit 1
fi

parent="$(git merge-base HEAD "${base_ref}")"
new_head=""

while read -r sha; do
  [[ -z "${sha}" ]] && continue
  tree="$(git rev-parse "${sha}^{tree}")"
  raw="$(git log -1 --format=%B "${sha}")"
  clean="$(printf '%s\n' "${raw}" | strip_cursor_lines)"
  if [[ -z "${clean//[$' \t\n']/}" ]]; then
    echo "error: commit ${sha} message empty after stripping cursor wording" >&2
    exit 1
  fi
  if printf '%s\n' "${clean}" | has_cursor; then
    echo "error: commit ${sha} still contains cursor after strip" >&2
    exit 1
  fi

  export GIT_AUTHOR_NAME
  export GIT_AUTHOR_EMAIL
  export GIT_AUTHOR_DATE
  GIT_AUTHOR_NAME="$(git log -1 --format=%an "${sha}")"
  GIT_AUTHOR_EMAIL="$(git log -1 --format=%ae "${sha}")"
  GIT_AUTHOR_DATE="$(git log -1 --format=%aI "${sha}")"

  new="$(printf '%s\n' "${clean}" | git commit-tree "${tree}" -p "${parent}" -F -)"
  parent="${new}"
  new_head="${new}"
done < <(git rev-list --reverse "${base_ref}..HEAD")

if [[ -z "${new_head}" ]]; then
  echo "rewritten: false"
  exit 0
fi

old_head="$(git rev-parse HEAD)"
git update-ref -m "scrub cursor trailers" HEAD "${new_head}" "${old_head}"

if git log "${base_ref}..HEAD" --format=%B | has_cursor; then
  echo "error: rewritten commits still contain cursor" >&2
  git log "${base_ref}..HEAD" --format=full >&2
  exit 1
fi

echo "rewritten: true"
echo "head: ${new_head}"
git log --oneline "${base_ref}..HEAD"
