# AgentFlow Python SDK

Typed client for the AgentFlow `/v1` HTTP API. The OpenAPI contract lives in
[`openapi/openapi.yaml`](../../openapi/openapi.yaml); regenerate REST stubs with
`scripts/gen/generate-sdks.sh` when the API changes.

## Install

```bash
cd sdk/python
pip install -e .
```

## Usage

```python
from agentflow_sdk import AgentFlowClient, subscribe_run_events

client = AgentFlowClient("http://localhost:8000", api_key="dev-admin")
run = client.create_run("01HZ...", input={"prompt": "hello"})
print(run.id, run.status)

for event in subscribe_run_events(
    "http://localhost:8000",
    run.id,
    api_key="dev-admin",
):
    print(event.type, event.data)
    if event.type.startswith("run."):
        break
```

`create_run` maps to `POST /v1/runs`. `subscribe_run_events` wraps the SSE
stream at `GET /v1/events/{run_id}` with optional `Last-Event-ID` replay.
