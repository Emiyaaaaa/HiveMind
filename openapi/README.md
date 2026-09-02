# OpenAPI spec and SDK generation

The AgentFlow HTTP contract is defined in [`openapi.yaml`](openapi.yaml), aligned
with [`docs/api-contract.md`](../docs/api-contract.md).

## Export from the Java API (springdoc)

When the Java API changes, refresh the checked-in spec:

```bash
scripts/gen/export-openapi.sh
```

This starts the Spring Boot API with the `openapi` profile (H2 in-memory DB),
downloads `/v3/api-docs.yaml`, and writes `openapi/openapi.yaml`.

Browse live docs at `http://localhost:8000/swagger-ui.html` while the API runs.

## Generate SDK stubs

Optional full REST client stubs (OpenAPI Generator):

```bash
scripts/gen/generate-sdks.sh
```

Requires Node (`npx`) and either Java or Docker. Output lands in:

- `sdk/python/generated/` — Python urllib3 client
- `sdk/typescript/generated/` — TypeScript fetch client

The supported consumer SDKs with `create_run` + SSE helpers live in:

- `sdk/python/src/agentflow_sdk/`
- `sdk/typescript/src/`

Regenerate those wrappers when the OpenAPI schemas change, or extend the
generator output and re-export thin helpers.
