# Hivemind SDKs

Official client libraries for the Hivemind HTTP API.

| Language | Package | Highlights |
| --- | --- | --- |
| Python | [`sdk/python`](python/) | `AgentFlowClient`: create / wait / cancel / retry / resume runs, message + thread pagination, audit trail; `subscribe_run_events` (SSE) |
| TypeScript | [`sdk/typescript`](typescript/) | `AgentFlowClient`: same surface (`createRun`, `waitForRun`, `retryRun`, `resumeRun`, threads, …); `subscribeRunEvents` (EventSource) |

Both clients cover the whole run lifecycle in `docs/api-contract.md`:
`POST /v1/runs` (with `thread_id`), `GET /v1/runs/{id}`, cancel, retry, resume,
`GET /v1/runs/{id}/messages`, `GET /v1/runs/{id}/audit`, and the `/v1/threads`
endpoints. `wait_for_run` / `waitForRun` poll until a terminal status **or**
`waiting_human`, so a human-approval script is `create → wait → resume → wait`.

`openapi/openapi.yaml` is exported from the Spring Boot API (`make gen-openapi`)
and currently predates the thread and audit endpoints; until it is
regenerated, `docs/api-contract.md` is the contract these clients follow.

The OpenAPI contract is in [`openapi/openapi.yaml`](../openapi/openapi.yaml).

## Regenerate

```bash
make gen-openapi   # export spec from Spring Boot (springdoc)
make gen-sdks      # optional full REST stubs via OpenAPI Generator
make sdk-test      # run SDK unit tests / typecheck
```

See [`openapi/README.md`](../openapi/README.md) for details.
