#!/usr/bin/env bash
# Re-apply a known-clean title/body onto the current branch PR, then verify
# the published title+body contain no cursor wording (platform may append
# "Made with Cursor" after gh pr create).
# Usage: scrub-pr.sh --title-file <file> --body-file <file>
set -euo pipefail

title_file=""
body_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --title-file)
      title_file="$2"
      shift 2
      ;;
    --body-file)
      body_file="$2"
      shift 2
      ;;
    *)
      echo "usage: scrub-pr.sh --title-file <file> --body-file <file>" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${title_file}" || -z "${body_file}" ]]; then
  echo "usage: scrub-pr.sh --title-file <file> --body-file <file>" >&2
  exit 2
fi
if [[ ! -f "${title_file}" || ! -f "${body_file}" ]]; then
  echo "error: title or body file missing" >&2
  exit 1
fi

has_cursor() {
  awk 'tolower($0) ~ /cursor/ { found=1 } END { exit found ? 0 : 1 }'
}

intended_title="$(cat "${title_file}")"
intended_body="$(cat "${body_file}")"

if printf '%s\n' "${intended_title}" "${intended_body}" | has_cursor; then
  echo "error: intended title/body still contain cursor wording; fix the files" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh not found" >&2
  exit 1
fi

gh pr edit --title "${intended_title}" --body-file "${body_file}" >/dev/null

viewed_title="$(gh pr view --json title --jq .title)"
viewed_body="$(gh pr view --json body --jq .body)"
url="$(gh pr view --json url --jq .url)"

if printf '%s\n' "${viewed_title}" "${viewed_body}" | has_cursor; then
  echo "error: published PR title/body still contain cursor after edit" >&2
  echo "title: ${viewed_title}" >&2
  echo "body:" >&2
  printf '%s\n' "${viewed_body}" >&2
  exit 1
fi

echo "pr_clean: true"
echo "url: ${url}"
