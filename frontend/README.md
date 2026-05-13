# AgentFlow console

Next.js 15 + React 19 admin UI for AgentFlow. Renders the run list, a run
detail view with step timeline, message stream and tool calls, plus a live
SSE log panel.

## Develop

```bash
cp .env.example .env.local
npm install
npm run dev
```

The dev server proxies `/api/*` to the FastAPI backend (default
`http://localhost:8000`).
