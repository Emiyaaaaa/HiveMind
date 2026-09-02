# AgentFlow SDKs

Official client libraries for the AgentFlow HTTP API.

| Language | Package | Highlights |
| --- | --- | --- |
| Python | [`sdk/python`](python/) | `AgentFlowClient.create_run`, `subscribe_run_events` (SSE) |
| TypeScript | [`sdk/typescript`](typescript/) | `AgentFlowClient.createRun`, `subscribeRunEvents` (EventSource) |

The OpenAPI contract is in [`openapi/openapi.yaml`](../openapi/openapi.yaml).

## Regenerate

```bash
make gen-openapi   # export spec from Spring Boot (springdoc)
make gen-sdks      # optional full REST stubs via OpenAPI Generator
make sdk-test      # run SDK unit tests / typecheck
```

See [`openapi/README.md`](../openapi/README.md) for details.
