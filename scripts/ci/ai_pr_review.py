#!/usr/bin/env python3
"""Analyze a pull request diff with an OpenAI-compatible LLM and post a review.

Designed for GitHub Actions. Reads configuration from environment variables,
fetches the PR metadata/diff via the GitHub API (no untrusted checkout), and
upserts a single review comment marked with AI_PR_REVIEW_MARKER.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

AI_PR_REVIEW_MARKER = "<!-- agentflow-ai-pr-review -->"
MAX_DIFF_CHARS = 120_000
MAX_COMMENT_CHARS = 65_000

# Explicit bot logins plus any login ending with "[bot]" (Dependabot, Renovate, …).
KNOWN_BOT_LOGINS = frozenset(
    {
        "dependabot",
        "dependabot[bot]",
        "renovate",
        "renovate[bot]",
        "github-actions",
        "github-actions[bot]",
        "copilot",
        "copilot[bot]",
        "imgbot",
        "imgbot[bot]",
        "snyk-bot",
        "snyk[bot]",
    }
)


def is_bot_author(login: str, user_type: str | None = None) -> bool:
    name = (login or "").strip().lower()
    if not name:
        return False
    if (user_type or "").lower() == "bot":
        return True
    if name.endswith("[bot]"):
        return True
    return name in KNOWN_BOT_LOGINS


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def github_request(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentflow-ai-pr-review",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
            if not body:
                return None
            if "json" in response.headers.get("Content-Type", ""):
                return json.loads(body)
            return body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API {method} {url} failed: {exc.code} {detail}") from exc


def llm_chat(base_url: str, api_key: str, model: str, messages: list[dict[str, str]]) -> str:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": messages,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "agentflow-ai-pr-review",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"LLM API failed: {exc.code} {detail}") from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit(f"Unexpected LLM response shape: {body!r}") from exc
    if not isinstance(content, str) or not content.strip():
        raise SystemExit("LLM returned empty content")
    return content.strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 80] + "\n\n…(truncated)…"


def build_prompt(title: str, body: str, author: str, base: str, head: str, diff: str) -> list[dict[str, str]]:
    system = """你是 AgentFlow（HiveMind）仓库的资深代码审查助手。
根据 PR 标题、描述和 diff，给出可执行的审查建议。

要求：
1. 用与 PR 描述相同的语言回复；若描述为空或中英混合，优先使用中文。
2. 关注：正确性、安全、API/数据模型破坏性变更、测试缺口、可维护性、与现有架构一致性。
3. 不要空泛赞美；没有严重问题时也要指出可改进点，或明确写“未发现明显问题”。
4. 输出使用 GitHub Markdown，结构固定为：
   ## 总结
   ## 主要建议（按优先级）
   ## 风险 / 测试建议
   ## 可选改进
5. 若能定位到具体文件，用 `path` 或 `path:line` 引用。
6. 不要编造 diff 中不存在的改动。
7. 不要输出密钥、token 或完整机密内容。"""

    user = f"""请审查以下 Pull Request。

作者: {author}
分支: {head} → {base}
标题: {title}

描述:
{body or "(无描述)"}

Diff:
```diff
{diff}
```
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def find_existing_comment(api_base: str, token: str, owner: str, repo: str, pr_number: int) -> int | None:
    url = f"{api_base}/repos/{owner}/{repo}/issues/{pr_number}/comments?per_page=100"
    comments = github_request("GET", url, token)
    if not isinstance(comments, list):
        return None
    for comment in comments:
        body = comment.get("body") or ""
        user = (comment.get("user") or {}).get("login") or ""
        if AI_PR_REVIEW_MARKER in body and user.endswith("[bot]"):
            return int(comment["id"])
        # Also match comments created with GITHUB_TOKEN (appears as github-actions[bot])
        if AI_PR_REVIEW_MARKER in body and "github-actions" in user:
            return int(comment["id"])
        if AI_PR_REVIEW_MARKER in body:
            return int(comment["id"])
    return None


def upsert_comment(
    api_base: str,
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
) -> None:
    existing_id = find_existing_comment(api_base, token, owner, repo, pr_number)
    if existing_id is None:
        github_request(
            "POST",
            f"{api_base}/repos/{owner}/{repo}/issues/{pr_number}/comments",
            token,
            {"body": body},
        )
        print(f"Created review comment on PR #{pr_number}")
        return

    github_request(
        "PATCH",
        f"{api_base}/repos/{owner}/{repo}/issues/comments/{existing_id}",
        token,
        {"body": body},
    )
    print(f"Updated review comment {existing_id} on PR #{pr_number}")


def main() -> int:
    token = env("GITHUB_TOKEN")
    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    repository = env("GITHUB_REPOSITORY")
    owner, repo = repository.split("/", 1)
    pr_number = int(env("PR_NUMBER"))

    llm_api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not llm_api_key:
        raise SystemExit("Set LLM_API_KEY or OPENAI_API_KEY")
    llm_base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    pr = github_request("GET", f"{api_base}/repos/{owner}/{repo}/pulls/{pr_number}", token)
    title = pr.get("title") or ""
    body = pr.get("body") or ""
    author_user = pr.get("user") or {}
    author = author_user.get("login") or "unknown"
    author_type = author_user.get("type")
    if is_bot_author(author, author_type):
        print(f"Skipping AI review for bot PR author: {author} (type={author_type})")
        return 0
    base = ((pr.get("base") or {}).get("ref")) or "main"
    head = ((pr.get("head") or {}).get("ref")) or "head"

    diff = github_request(
        "GET",
        f"{api_base}/repos/{owner}/{repo}/pulls/{pr_number}",
        token,
        accept="application/vnd.github.v3.diff",
    )
    if not isinstance(diff, str) or not diff.strip():
        review_md = (
            f"{AI_PR_REVIEW_MARKER}\n"
            "## AI PR Review\n\n"
            "未获取到可分析的 diff（可能是空 PR 或文件过大）。"
        )
        upsert_comment(api_base, token, owner, repo, pr_number, review_md)
        return 0

    diff = truncate(diff, MAX_DIFF_CHARS)
    messages = build_prompt(title, truncate(body, 8_000), author, base, head, diff)
    analysis = llm_chat(llm_base_url, llm_api_key, llm_model, messages)
    # Strip accidental marker duplication from model output
    analysis = re.sub(re.escape(AI_PR_REVIEW_MARKER), "", analysis).strip()
    analysis = truncate(analysis, MAX_COMMENT_CHARS - 500)

    review_md = (
        f"{AI_PR_REVIEW_MARKER}\n"
        f"## AI PR Review\n\n"
        f"_Model: `{llm_model}` · automatic suggestions for contributor PRs_"
        f"\n\n{analysis}\n"
    )
    upsert_comment(api_base, token, owner, repo, pr_number, review_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
