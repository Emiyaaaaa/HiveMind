# AgentFlow TypeScript SDK

Typed client for the AgentFlow `/v1` HTTP API. The OpenAPI contract lives in
[`openapi/openapi.yaml`](../../openapi/openapi.yaml).

## Install

```bash
cd sdk/typescript
npm install
npm run build
```

## Usage

```ts
import { AgentFlowClient, subscribeRunEvents } from "@agentflow/sdk";

const client = new AgentFlowClient({
  baseUrl: "http://localhost:8000",
  apiKey: "dev-admin",
});

const run = await client.createRun({
  agent_id: "01HZ...",
  input: { prompt: "hello" },
});

const subscription = subscribeRunEvents("http://localhost:8000", run.id, {
  apiKey: "dev-admin",
  onEvent: (event) => console.log(event.type, event.data),
});

// subscription.close() when done
```

`createRun` maps to `POST /v1/runs`. `subscribeRunEvents` wraps the SSE stream
at `GET /v1/events/{run_id}` (browser `EventSource` with reconnect).

Regenerate full REST stubs from the OpenAPI spec with
`scripts/gen/generate-sdks.sh`.
